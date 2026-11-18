from . import models
from . import wizard


def _ss_post_init_hook(env):
    """Initialise the Smart Sales fields on existing records.

    * opportunities are flagged as Converted, lost leads as Unqualified,
      leads with done activities as Working;
    * lead scores (and so ratings) are computed from the default rules.
    """
    cr = env.cr
    cr.execute("UPDATE crm_lead SET ss_score = 0 WHERE ss_score IS NULL")
    cr.execute("""
        UPDATE crm_lead SET ss_lead_status = 'converted'
         WHERE type = 'opportunity'
    """)
    cr.execute("""
        UPDATE crm_lead SET ss_lead_status = 'unqualified'
         WHERE type = 'lead' AND won_status = 'lost'
    """)
    cr.execute("""
        UPDATE crm_lead lead SET ss_lead_status = 'working'
         WHERE lead.type = 'lead' AND lead.ss_lead_status = 'new'
           AND EXISTS (SELECT 1 FROM mail_activity act
                        WHERE act.res_model = 'crm.lead' AND act.res_id = lead.id
                          AND act.active IS NOT TRUE AND act.date_done IS NOT NULL)
    """)
    cr.execute("UPDATE crm_lead SET ss_status_date = COALESCE(write_date, create_date) WHERE ss_status_date IS NULL")
    env['crm.lead'].invalidate_model(['ss_lead_status', 'ss_status_date'])
    env['crm.lead'].with_context(active_test=False)._ss_cron_recompute_scores()
