# R&D: Salesforce Lightning vs Odoo 20 CRM

Reference sources used:
- Salesforce Trailhead: *Create and Convert Leads* (Lightning), *Build a Custom Record Page*, *Explore the New Sales Tools* (Lightning migration)
- admin.salesforce.com: *Tailor the Activity Timeline for Lightning Experience users*
- Salesforce Help: Lead conversion (`leads_convert.htm`), Lead Assignment Rules, Duplicate/Matching rules, Path
- Salesforce Lightning Design System (SLDS): colours (brand `#0176D3`), cards, path, badges and activity timeline patterns
- Odoo 20 source code: `odoo/addons/crm`, `sales_team`, `mail`, `calendar`, `web`, `odoo/addons/base`. This is the developer's local copy, the same code as branch `20.0`.

## 1. Odoo 20 technical findings that matter for this module

| Area | Odoo 20 reality (verified in source) | Consequence |
|---|---|---|
| Access rights | `ir.model.access` + `ir.rule` replaced by **`ir.access`**, loaded from `security/ir.access.csv` (`id,name,model_id,group_id/id,operation,domain`). A row with a group grants a permission; a row without a group is a restriction. | Module uses `security/ir.access.csv` |
| System parameters | `get_param/set_param` removed, replaced by **typed** `get_bool/get_int/get_str/set_*` | Settings read with the typed API |
| Frontend | **OWL 3** (`3.0.0-alpha`): no `useState` (use `proxy()`/`signal()`), `props = useProps({...})` with `t.*` validators, templates prefix every member with `this.`, no JS globals (e.g. `String`) in templates, `t-model.proxy` | Components written for OWL 3 |
| Icons | Font Awesome removed. Use `<i class="oi" data-icon="name"/>`, a **subset** of Material Symbols (~480 names in `web/tooling/icons/icons_wishlist.txt`), and buttons use `icon="east"` | Only icons from the subset are used, and each has a title (a11y check) |
| Views | Inherited (extension) views **cannot** have `group_ids` | Lightning UI is applied for everybody once installed |
| Partners | `res.partner.is_company` is now **computed** (commercial partner with a VAT) | "Account" = commercial entity (partner without parent) |
| Lead conversion | The single-lead "Convert to Opportunity" button converts directly (no wizard). The mass wizard still exists | Our *Convert* dialog fills the Salesforce gap. The original button is kept as *Quick Convert* |
| Native features | `won_status` (stored), predictive lead scoring (PLS) probability, rule-based team assignment (`crm.team.member.assignment_domain` + cron), duplicates & merge, rotting stages, forecast, recurring revenue, lead properties, activity plans, smart calendar | Not duplicated; the module builds on them |

## 2. Feature comparison

| # | Feature | Salesforce Lightning | Odoo 20 (standard) | Action taken |
|---|---|---|---|---|
| 1 | Lead Kanban | Kanban by Lead Status, summarised amounts | Lead kanban: minimal card, no grouping | **Improved**: grouped by Lead Status, drag & drop, rich card (company, contact, email, phone, source, rating, score, revenue, created on, next activity), quick create |
| 2 | Lead List | List views, inline edit, mass actions | List, optional columns, favorites, export, mass edit | **Improved**: status/rating/score columns, Change Owner / Change Status / Run Assignment Rules, predefined list views (My Open Leads, All Open, Today's, Hot/Warm/Cold, by status) |
| 3 | Lead Detail | Highlights panel, Path, tabs Activity/Details/Related | Form + notebook; address/contact info only in debug mode | **Improved**: highlights panel, Lead Status path, Activity / Details (Lead, Address, System info) / Lead Score tabs, duplicate banner |
| 4 | Path guidance | Key Fields + Guidance for Success per stage | Stage "requirements" tooltip | **New**: Key Fields and Guidance per `crm.stage` on the opportunity page |
| 5 | Lead Status | Open, Working, Nurturing, Qualified / Unqualified, Converted | No lead status (type + won/lost only) | **New** `ss_lead_status` with automatic transitions |
| 6 | Lead Rating | Hot / Warm / Cold | Priority stars only | **New** `ss_rating`, computed from score, can be overridden |
| 7 | Lead Scoring | Einstein (AI) / Account Engagement rule grading | PLS: AI win probability | **New** rule-based fit/engagement score (0-100) with breakdown. PLS is kept |
| 8 | Assignment Rules | Ordered rule entries, first match, user/queue, notify | Periodic, capacity-based team assignment | **New** instant, ordered first-match rules: user / round robin / team workload, follow-up activity, notification. Native assignment is kept |
| 9 | Lead Conversion | Dialog: Account, Contact, Opportunity (new or existing), owner | Direct convert / mass wizard | **New** Salesforce-style Convert dialog (create or choose account, create or choose contact, new opportunity or merge into an existing one) |
| 10 | Activity Timeline | Composer + Upcoming & Overdue + past by month, filters, expand all | Chatter (messages + activities) | **New** timeline widget on top of `mail.activity`, `mail.message` and `calendar.event`. No separate activity system. Chatter is kept |
| 11 | Log a Call | Logged call record | Activity of type Call, marked done | **New** quick dialog (outcome, comments, follow-up) creating a done Call activity |
| 12 | Duplicate detection | Duplicate & matching rules (alert / block) | Similar-leads smart button, merge | **Improved**: alert banner + optional *block* rule on email |
| 13 | Workflow automation | Flow, stage-based actions | Automation rules (`base_automation`), activity plans | **New** stage-entry activity + stale lead follow-up cron (no `base.automation` code actions needed) |
| 14 | Reports & Dashboards | Lightning dashboards | Graph/pivot reports, forecast | **New** Sales Dashboard (KPIs, charts, drill-down, leaderboard, filters) |
| 15 | Sales forecasting | Forecasts tab | Forecast report (prorated revenue by closing month) | **Reused** in the dashboard (expected vs weighted by month). Standard forecast kept |
| 16 | Email integration / templates / tracking | Gmail/Outlook, templates, tracking | Mail gateway, templates, Outlook/Gmail plugins, mass mailing | **Reused**: Email from the timeline opens the standard composer |
| 17 | Calendar | Events | `calendar.event` + smart calendar | **Reused**: New Event opens the standard meeting scheduler |
| 18 | Campaigns / source tracking | Campaigns, influence | UTM campaign/medium/source | **Reused**: shown on cards, details, dashboard filters |
| 19 | Accounts / Contacts | Account and Contact objects | `res.partner` hierarchy | **Reused** by the Convert dialog |
| 20 | Role-based access | Profiles, sharing rules | Groups + `ir.access` | **Reused**. New models secured with `ir.access` (manager CRUD, salesman read, multi-company restriction) |
| 21 | Import / Export / Mass update | Data Import Wizard, mass update | Import/export, multi-edit | **Reused** + mass actions wizard |
| 22 | Record history | Field history tracking | Field tracking in chatter | **Reused**. Lead Status and Rating are tracked |

## 3. Not implemented and why

| Salesforce capability | Reason |
|---|---|
| Einstein AI scoring / activity capture | Needs Salesforce AI services. Odoo's own PLS already gives AI-like probability |
| Email open/click tracking for 1:1 emails | Needs a tracking pixel and link-rewriting infrastructure. Odoo provides it for mass mailing only (`mass_mailing` app) |
| Gmail/Outlook sync of 1:1 mailboxes | Covered by Odoo's own mail plugins / Microsoft & Google sync modules (external services) |
| Queues (assignment to queues) | Odoo's equivalent is the sales team, so rules can assign to a team (workload based) |
| Lightning App Builder (drag & drop page layouts) | Out of scope. Odoo Studio covers layout customisation (Enterprise) |
| Territory management, CPQ, Sales Engagement cadences | Separate products; Odoo activity plans cover simple cadences |
