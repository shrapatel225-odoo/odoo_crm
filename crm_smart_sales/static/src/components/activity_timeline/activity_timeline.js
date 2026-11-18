import { Component, markup, onWillStart, onWillUpdateProps, proxy, useProps } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { deserializeDate, deserializeDateTime, formatDate, formatDateTime } from "@web/core/l10n/dates";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

const { DateTime } = luxon;

const KIND_ICONS = {
    call: "phone_in_talk",
    email: "mail",
    meeting: "calendar_today",
    task: "task",
    note: "sticky_note_2",
};

/**
 * Activity tab: composer + Upcoming & Overdue +
 * Past Activity grouped by month. Data comes from the standard
 * mail.activity / mail.message / calendar.event records of the lead.
 */
export class SsActivityTimeline extends Component {
    static template = "crm_smart_sales.ActivityTimeline";

    props = useProps(standardWidgetProps);

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = proxy({
            loading: true,
            upcoming: [],
            past: [],
            filter: "all",
            expanded: {},
            expandAll: false,
            noteOpen: false,
            noteBody: "",
        });
        this.lastKey = null;
        onWillStart(() => this.load(this.props.record));
        onWillUpdateProps((nextProps) => {
            if (this.keyOf(nextProps.record) !== this.lastKey) {
                return this.load(nextProps.record);
            }
        });
    }

    keyOf(record) {
        const writeDate = record.data.write_date;
        return `${record.resId || "new"}-${writeDate ? writeDate.toMillis?.() || writeDate : ""}`;
    }

    get resId() {
        return this.props.record.resId;
    }

    async load(record = this.props.record) {
        this.lastKey = this.keyOf(record);
        if (!record.resId) {
            this.state.upcoming = [];
            this.state.past = [];
            this.state.loading = false;
            return;
        }
        this.state.loading = true;
        const data = await this.orm.call("crm.lead", "ss_get_timeline", [record.resId]);
        this.state.upcoming = data.upcoming;
        this.state.past = data.past;
        this.state.loading = false;
    }

    // ------------------------------------------------------------------
    // Getters
    // ------------------------------------------------------------------

    get filters() {
        return [
            { key: "all", label: _t("All") },
            { key: "email", label: _t("Emails") },
            { key: "call", label: _t("Calls") },
            { key: "meeting", label: _t("Meetings") },
            { key: "task", label: _t("Tasks") },
            { key: "note", label: _t("Notes") },
        ];
    }

    matches(item) {
        return this.state.filter === "all" || item.kind === this.state.filter;
    }

    get upcomingItems() {
        return this.state.upcoming.filter((item) => this.matches(item));
    }

    get pastGroups() {
        const groups = [];
        const byKey = {};
        const now = DateTime.local();
        for (const item of this.state.past) {
            if (!this.matches(item)) {
                continue;
            }
            const date = this.parseDate(item.date);
            const key = date ? date.toFormat("yyyy-MM") : "none";
            if (!byKey[key]) {
                let label;
                if (!date) {
                    label = _t("No date");
                } else if (key === now.toFormat("yyyy-MM")) {
                    label = _t("This Month");
                } else if (key === now.minus({ months: 1 }).toFormat("yyyy-MM")) {
                    label = _t("Last Month");
                } else {
                    label = date.toFormat("LLLL yyyy");
                }
                byKey[key] = { key, label, items: [] };
                groups.push(byKey[key]);
            }
            byKey[key].items.push(item);
        }
        return groups;
    }

    get isEmpty() {
        return !this.upcomingItems.length && !this.pastGroups.length;
    }

    parseDate(value) {
        if (!value) {
            return null;
        }
        return value.length > 10 ? deserializeDateTime(value) : deserializeDate(value);
    }

    displayDate(item) {
        const date = this.parseDate(item.date);
        if (!date) {
            return "";
        }
        return item.date.length > 10 ? formatDateTime(date) : formatDate(date);
    }

    icon(item) {
        return KIND_ICONS[item.kind] || "task";
    }

    itemKey(item) {
        return `${item.model}_${item.id}`;
    }

    isExpanded(item) {
        return this.state.expandAll || !!this.state.expanded[this.itemKey(item)];
    }

    noteMarkup(item) {
        return markup(item.note || "");
    }

    // ------------------------------------------------------------------
    // Handlers
    // ------------------------------------------------------------------

    setFilter(key) {
        this.state.filter = key;
    }

    toggleExpandAll() {
        this.state.expandAll = !this.state.expandAll;
        this.state.expanded = {};
    }

    toggleItem(item) {
        const key = this.itemKey(item);
        this.state.expanded[key] = !this.state.expanded[key];
    }

    async ensureSaved() {
        const record = this.props.record;
        if (record.isNew || (await record.isDirty())) {
            const saved = await record.save();
            if (!saved) {
                return false;
            }
        }
        if (!record.resId) {
            this.notification.add(_t("Save the record before logging activities."), { type: "warning" });
            return false;
        }
        return true;
    }

    async refresh() {
        await this.props.record.load();
        await this.load(this.props.record);
    }

    async openServerAction(method) {
        if (!(await this.ensureSaved())) {
            return;
        }
        const action = await this.orm.call("crm.lead", method, [[this.resId]]);
        await this.action.doAction(action, { onClose: () => this.refresh() });
    }

    onLogCall() {
        return this.openServerAction("action_ss_log_call");
    }

    onSendEmail() {
        return this.openServerAction("action_ss_send_email");
    }

    onNewTask() {
        return this.openServerAction("action_ss_new_task");
    }

    async onNewEvent() {
        if (!(await this.ensureSaved())) {
            return;
        }
        const action = await this.orm.call("crm.lead", "action_schedule_meeting", [[this.resId]]);
        await this.action.doAction(action);
    }

    onToggleNote() {
        this.state.noteOpen = !this.state.noteOpen;
    }

    onNoteInput(ev) {
        this.state.noteBody = ev.target.value;
    }

    async onSaveNote() {
        const body = (this.state.noteBody || "").trim();
        if (!body || !(await this.ensureSaved())) {
            return;
        }
        await this.orm.call("crm.lead", "message_post", [[this.resId]], {
            body,
            message_type: "comment",
            subtype_xmlid: "mail.mt_note",
        });
        this.state.noteBody = "";
        this.state.noteOpen = false;
        await this.refresh();
    }

    async onMarkDone(item) {
        if (item.model !== "mail.activity") {
            return;
        }
        await this.orm.call("mail.activity", "action_feedback", [[item.id]], { feedback: "" });
        await this.refresh();
    }

    async onOpenItem(item) {
        if (item.model === "calendar.event") {
            await this.action.doAction({
                type: "ir.actions.act_window",
                res_model: "calendar.event",
                res_id: item.id,
                views: [[false, "form"]],
                target: "current",
            });
        } else {
            this.toggleItem(item);
        }
    }
}

registry.category("view_widgets").add("ss_activity_timeline", {
    component: SsActivityTimeline,
});
