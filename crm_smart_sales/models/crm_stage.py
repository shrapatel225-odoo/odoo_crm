from odoo import fields, models


class CrmStage(models.Model):
    """Path settings on pipeline stages.

    * Key Fields & Guidance for Success: displayed on the opportunity record
      page for the current stage, to coach sales reps.
    * Stage-based action: automatically schedule an activity for the
      salesperson when an opportunity enters the stage.
    """
    _inherit = 'crm.stage'

    ss_guidance = fields.Html(
        'Guidance for Success', translate=True, sanitize=True,
        help="Coaching tips displayed on the record page when an opportunity is in this stage.")
    ss_key_field_ids = fields.Many2many(
        'ir.model.fields', 'crm_stage_ss_key_field_rel', 'stage_id', 'field_id',
        string='Key Fields',
        domain="[('model', '=', 'crm.lead'), ('store', '=', True), "
               "('ttype', 'not in', ['one2many', 'binary', 'properties', 'properties_definition', 'json'])]",
        help="Fields highlighted on the record page while the opportunity is in this stage.")
    ss_activity_type_id = fields.Many2one(
        'mail.activity.type', string='Activity on Entry',
        domain="['|', ('res_model', '=', False), ('res_model', '=', 'crm.lead')]",
        help="When an opportunity enters this stage, this activity is scheduled for its salesperson.")
    ss_activity_summary = fields.Char('Activity Summary', translate=True)
    ss_activity_days = fields.Integer('Activity Due In (days)', default=2)
