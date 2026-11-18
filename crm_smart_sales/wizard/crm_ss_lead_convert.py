from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import clean_context


class CrmSsLeadConvert(models.TransientModel):
    """"Convert Lead" dialog.

    Lets the rep decide, in one screen, what happens with the Account
    (company), the Contact (person) and the Opportunity. It relies on the standard Odoo conversion API
    (``convert_opportunity`` / ``_merge_opportunity``) so all standard
    behaviours (stage, team, date_conversion, merge of chatter...) are kept.
    """
    _name = 'crm.ss.lead.convert'
    _description = 'Convert Lead'

    lead_id = fields.Many2one('crm.lead', string='Lead', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='lead_id.company_id')

    account_action = fields.Selection([
        ('create', 'Create New Account'),
        ('existing', 'Choose Existing Account'),
        ('none', 'No Account (individual)'),
    ], string='Account', required=True, default='create')
    account_name = fields.Char('Account Name')
    account_id = fields.Many2one('res.partner', string='Existing Account',
                                 domain="[('parent_id', '=', False)]",
                                 help="Commercial entity (company) the contact belongs to.")

    contact_action = fields.Selection([
        ('create', 'Create New Contact'),
        ('existing', 'Choose Existing Contact'),
    ], string='Contact', required=True, default='create')
    contact_name = fields.Char('Contact Name')
    contact_id = fields.Many2one('res.partner', string='Existing Contact')

    opportunity_action = fields.Selection([
        ('create', 'Create New Opportunity'),
        ('merge', 'Merge with Existing Opportunity'),
    ], string='Opportunity', required=True, default='create')
    opportunity_name = fields.Char('Opportunity Name')
    merge_opportunity_id = fields.Many2one(
        'crm.lead', string='Existing Opportunity',
        domain="[('type', '=', 'opportunity'), ('won_status', '=', 'pending'), ('id', '!=', lead_id)]")
    suggested_opportunity_ids = fields.Many2many('crm.lead', compute='_compute_suggestions',
                                                 string='Matching Opportunities')
    suggested_account_count = fields.Integer(compute='_compute_suggestions')

    user_id = fields.Many2one('res.users', string='Record Owner', domain="[('share', '=', False)]")
    team_id = fields.Many2one('crm.team', string='Sales Team')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        lead_id = self.env.context.get('active_id') if self.env.context.get('active_model') == 'crm.lead' else False
        lead_id = res.get('lead_id') or lead_id
        if not lead_id:
            return res
        lead = self.env['crm.lead'].browse(lead_id)
        if lead.type != 'lead':
            raise UserError(_("Only leads can be converted."))
        res['lead_id'] = lead.id
        res['user_id'] = lead.user_id.id or self.env.user.id
        res['team_id'] = lead.team_id.id
        res['opportunity_name'] = lead.name
        res['contact_name'] = lead.contact_name or (lead.partner_id.parent_id and lead.partner_id.name) or False

        partner = lead.partner_id
        account_name = lead.partner_name or (partner.parent_id and partner.commercial_partner_id.name) or False
        res['account_name'] = account_name

        # Odoo 20: the "account" is the commercial entity (partner without parent);
        # ``is_company`` is now computed from the VAT and cannot be relied upon.
        existing_account = self.env['res.partner']
        existing_contact = self.env['res.partner']
        if partner:
            if partner.parent_id:
                existing_account = partner.commercial_partner_id
                existing_contact = partner
            elif lead.partner_name and partner.name == lead.partner_name:
                existing_account = partner
            else:
                existing_contact = partner
        if not existing_account and account_name:
            existing_account = self.env['res.partner'].search(
                [('parent_id', '=', False), ('name', '=ilike', account_name)], limit=1)
        if not existing_contact:
            matching = lead._find_matching_partner()
            if matching and matching != existing_account:
                existing_contact = matching

        if existing_account:
            res['account_action'] = 'existing'
            res['account_id'] = existing_account.id
        elif not account_name:
            res['account_action'] = 'none'
        if existing_contact:
            res['contact_action'] = 'existing'
            res['contact_id'] = existing_contact.id
        return res

    @api.depends('lead_id', 'account_name')
    def _compute_suggestions(self):
        for wizard in self:
            lead = wizard.lead_id
            if not lead:
                wizard.suggested_opportunity_ids = False
                wizard.suggested_account_count = 0
                continue
            duplicates = lead._get_lead_duplicates(partner=lead.partner_id, email=lead.email_from)
            wizard.suggested_opportunity_ids = duplicates.filtered(
                lambda l: l.type == 'opportunity' and l.won_status == 'pending' and l != lead)
            wizard.suggested_account_count = self.env['res.partner'].search_count(
                [('parent_id', '=', False), ('name', 'ilike', wizard.account_name)]) if wizard.account_name else 0

    def _ss_get_account(self):
        self.ensure_one()
        lead = self.lead_id
        Partner = self.env['res.partner'].with_context(clean_context(self.env.context))
        if self.account_action == 'existing':
            if not self.account_id:
                raise UserError(_("Please select the existing account."))
            return self.account_id
        if self.account_action == 'create':
            if not self.account_name:
                raise UserError(_("Please enter the account name."))
            vals = lead._prepare_customer_values(self.account_name)
            vals.update({'function': False, 'email': False,
                         'user_id': self.user_id.id or vals.get('user_id')})
            vals.pop('parent_name', None)
            return Partner.create(vals)
        return Partner

    def _ss_get_contact(self, account):
        self.ensure_one()
        lead = self.lead_id
        Partner = self.env['res.partner'].with_context(clean_context(self.env.context))
        if self.contact_action == 'existing':
            if not self.contact_id:
                raise UserError(_("Please select the existing contact."))
            contact = self.contact_id
            if account and not contact.parent_id and contact != account:
                contact.parent_id = account
            return contact
        name = self.contact_name or lead.contact_name or lead.email_from or lead.name
        vals = lead._prepare_customer_values(name, parent_id=account.id if account else False)
        vals.pop('parent_name', None)
        if self.user_id:
            vals['user_id'] = self.user_id.id
        return Partner.create(vals)

    def action_convert(self):
        self.ensure_one()
        lead = self.lead_id
        if lead.type != 'lead' or not lead.active:
            raise UserError(_("This lead was already converted or is not active."))
        if self.opportunity_action == 'merge' and not self.merge_opportunity_id:
            raise UserError(_("Please select the opportunity to merge with."))

        account = self._ss_get_account()
        contact = self._ss_get_contact(account)
        customer = contact or account

        if self.opportunity_action == 'merge':
            target = self.merge_opportunity_id
            lead.write({'partner_id': customer.id})
            lead.convert_opportunity(customer, user_ids=False, team_id=False)
            result = (target | lead)._merge_opportunity(
                user_id=self.user_id.id or False, team_id=self.team_id.id or False)
        else:
            if self.opportunity_name:
                lead.name = self.opportunity_name
            lead.convert_opportunity(
                customer,
                user_ids=self.user_id.ids or False,
                team_id=self.team_id.id or False,
            )
            result = lead

        if result.exists() and result.ss_lead_status != 'converted':
            result.ss_lead_status = 'converted'
        result.message_post(
            body=_("Lead converted: account %(account)s, contact %(contact)s.",
                   account=account.display_name or _('none'), contact=contact.display_name or _('none')),
            subtype_xmlid='mail.mt_note',
        )
        return result.redirect_lead_opportunity_view()
