Smart Sales CRM (crm_smart_sales) for Odoo 20
Modern, enterprise-grade CRM experience for Odoo 20 (Community & Enterprise). Author: Donika Enterprise. Support: shra.patel225@gmail.com. Price: 200 EUR. License: OPL-1.

Technical notes and the standard Odoo 20 vs Smart Sales CRM comparison: see doc/RESEARCH.md.

1. Features already available in Odoo 20 (reused, not duplicated)
Pipeline kanban, predictive lead scoring (probability), team-based lead assignment (cron), duplicates & merge, rotting stages, forecast, lost reasons, UTM campaign/medium/source, activity types & plans, chatter, field tracking, smart calendar, email composer/templates, import/export, multi-company, access groups.

2. Features improved
Lead record page: highlights panel (type, status, rating, score, owner, company, phone, email, last activity), Lead Status path in the header, Convert button, duplicate alert banner, Activity / Details / Lead Score tabs (address & contact data visible without debug mode).
Opportunity record page: Path assistant with Key Fields and Guidance for Success of the current stage.
Pipeline kanban: company, rating badge, email, phone, source, next activity with due date.
Lead kanban: grouped by Lead Status (drag & drop), rich cards, quick create, revenue progress bar.
Lists: status/rating/score columns, activities, mass actions (Change Owner, Change Status, Run Assignment Rules).
Search: My Open Leads, All Open Leads, Today's Leads, Hot/Warm/Cold, status filters, group by Status/Rating.
Duplicate detection: alert banner, optional block rule (same email on an open lead).
3. New functionality
Feature	Where
Lead Status (New, Working, Nurturing, Qualified, Unqualified, Converted) with automatic transitions (activity done / email sent → Working, conversion → Converted, lost → Unqualified, restore → Working)	models/crm_lead.py
Lead Score 0-100 from configurable rules + breakdown, Hot/Warm/Cold rating (thresholds in Settings, manual override)	models/crm_ss_scoring_rule.py, models/crm_lead.py
Lead Assignment Rules: ordered first match, specific user / round robin / least loaded team member, follow-up activity, notification, manual run	models/crm_ss_assignment_rule.py
Convert Lead dialog (Account, Contact, Opportunity new or merge, owner, team)	wizard/crm_ss_lead_convert.py
Activity timeline (Log a Call, Email, New Task, New Event, Note; Upcoming & Overdue; past by month; filters; expand all; mark done)	static/src/components/activity_timeline/
Log a Call dialog (outcome, comments, follow-up)	wizard/crm_ss_log_call.py
Stage-based action (activity on stage entry) and stage path guidance	models/crm_stage.py
Stale lead follow-up (daily cron) and daily score recomputation	data/ir_cron_data.xml
Mass update wizard (owner, status, rating, team, rules)	wizard/crm_ss_mass_update.py
Sales Dashboard: 8 KPIs + 6 secondary KPIs, 10 Chart.js charts with drill-down, leaderboard, filters (date range, salesperson, team, source, status, company)	models/crm_ss_dashboard.py, static/src/components/dashboard/
Menus: CRM → Dashboard, CRM → Reporting → Sales Dashboard, CRM → Configuration → Lead Rules → Assignment Rules / Scoring Rules. Settings: Settings → CRM → Smart Sales CRM.

4. Files created
crm_smart_sales/
├── __init__.py                 (post-init hook: initialises status/score of existing records)
├── __manifest__.py
├── README.md, doc/RESEARCH.md
├── data/  crm_ss_data.xml (12 default scoring rules), ir_cron_data.xml, crm_ss_demo.xml
├── models/ crm_lead.py, crm_stage.py, crm_ss_scoring_rule.py, crm_ss_assignment_rule.py,
│           crm_ss_dashboard.py, mail_activity.py, res_config_settings.py
├── wizard/ crm_ss_lead_convert.py(+views), crm_ss_mass_update.py(+views), crm_ss_log_call.py(+views)
├── views/  crm_lead_views.xml, crm_stage_views.xml, crm_ss_scoring_rule_views.xml,
│           crm_ss_assignment_rule_views.xml, res_config_settings_views.xml,
│           crm_ss_dashboard_views.xml, crm_ss_menus.xml
├── security/ir.access.csv
├── static/description/ icon.png, banner.png, index.html, screenshots/
├── static/src/scss/smart_sales.scss
├── static/src/components/dashboard/ dashboard.js/.xml/.scss, chart_card.js
├── static/src/components/activity_timeline/ activity_timeline.js/.xml/.scss
└── tests/test_crm_smart_sales.py (24 tests)
5. Files modified
None. No Odoo core file is changed; everything uses inheritance (_inherit, inherited views, asset bundle).

6. Installation
Copy crm_smart_sales into a custom addons path (e.g. D:\workspace\project\20_odoo\apps).
Ensure that path is in addons_path. Restart Odoo.
Apps → Update Apps List → search "Smart Sales" or "CRM" → Install (or odoo-bin -d <db> -i crm_smart_sales).
Optional: Settings → CRM → Smart Sales CRM; Configuration → Lead Rules; on stages, fill Path and Stage-based Action. Enable Leads in CRM settings to use the lead kanban/list (standard Odoo setting).
7. Upgrade
odoo-bin -d <db> -u crm_smart_sales (or Apps → Upgrade). Default scoring rules are noupdate, so your changes are kept.

8. Testing results (Odoo 20.0, PostgreSQL 16, Python 3.13)
Installation on a database with demo data and on an empty database: OK, no warnings. Upgrade (-u): OK.
Module test suite: 24/24 passed (status lifecycle, scoring & rating, assignment round robin / first match / team workload / setting, conversion (create / existing account + merge / only leads), stage activity & path, stale follow-up cron, log a call & timeline, duplicate alert/block, mass update, dashboard figures & drill-down, record rules for salesmen, access rights on rule models).
Standard Odoo CRM test suite run with the module installed: 136/138 passed (baseline without module 138/138). The 2 differences (TestLeadLost.test_lead_lost*) assert exactly 3 tracked fields when a lead is lost; the module adds a 4th tracked value Lead Status: New → Unqualified. This is intended field history, not a regression. Earlier query-count regressions in the assignment performance tests were fixed (score recomputation is only triggered by fields used in scoring rules).
Browser end-to-end (Chromium): lead page, Log a Call, Note, New Task dialog, status path, Convert dialog → opportunity, lead kanban drag & drop between statuses, list mass action, dashboard KPI drill-down, settings, rule forms: all passed with 0 JavaScript console errors and no server errors.
Large database test (100,000 leads/opportunities + 20,000 activities)
Install time: 31 s. Existing data unchanged: checksums of every standard crm.lead column (name, stage, salesperson, revenue, probability, partner, email, phone, won/lost, dates, write_date…), mail.activity, res.partner and crm.stage are identical before and after install. 0 chatter messages added on leads, 0 records with a modified "Last Updated" date.
New columns are filled in SQL by the install hook: Lead Status, Lead Score, Rating, status date.
Dashboard on 100k records: 0.8 s. Daily score cron: 3 s. Lead creation: 0.05 s.
9. Uninstall
Uninstalling removes only the module's own data (Lead Status, Score, Rating, rules, stage guidance). Standard CRM data is not touched. Take a database backup before uninstalling if you want to keep that history.

10. Known limitations
The new CRM look applies to all users (Odoo 20 does not allow group-restricted inherited views).
Dashboard monetary totals are summed in the company currency of each record without conversion (same as standard Odoo reports).
Lead Status is meaningful for leads. Opportunities created directly are flagged Converted.
Email open/click tracking for individual emails, AI scoring and mailbox sync rely on external services (see doc/RESEARCH.md).
