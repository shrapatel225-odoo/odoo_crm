import { Component, onWillStart, proxy, toRaw, useProps } from "@odoo/owl";
import { formatCurrency } from "@web/core/currency";
import { _t } from "@web/core/l10n/translation";
import { serializeDate } from "@web/core/l10n/dates";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Layout } from "@web/search/layout";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";
import { SsChartCard } from "./chart_card";

const { DateTime } = luxon;

// Dashboard palette
const SS_COLORS = [
    "#0176D3", "#06A59A", "#FE9339", "#BA01FF", "#3BA755",
    "#EA001E", "#0B5CAB", "#7F8DE1", "#DD7A01", "#04844B",
    "#9050E9", "#FF538A",
];
const STATUS_COLORS = {
    new: "#0176D3",
    working: "#1B96FF",
    nurturing: "#FE9339",
    qualified: "#3BA755",
    unqualified: "#EA001E",
    converted: "#04844B",
};
const RATING_COLORS = { hot: "#EA001E", warm: "#FE9339", cold: "#0176D3" };

export class SsCrmDashboard extends Component {
    static template = "crm_smart_sales.Dashboard";
    static components = { Layout, SsChartCard };

    props = useProps(standardActionServiceProps);

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = proxy({
            loading: true,
            options: null,
            data: null,
            preset: "this_year",
            dateFrom: "",
            dateTo: "",
            userId: "",
            teamId: "",
            sourceId: "",
            status: "",
            companyId: "",
        });
        this.applyPreset("this_year");
        onWillStart(async () => {
            this.state.options = await this.orm.call("crm.ss.dashboard", "get_filter_options", []);
            await this.loadData();
        });
    }

    // ------------------------------------------------------------------
    // Filters
    // ------------------------------------------------------------------

    get presets() {
        return [
            { key: "this_month", label: _t("This Month") },
            { key: "last_month", label: _t("Last Month") },
            { key: "this_quarter", label: _t("This Quarter") },
            { key: "this_year", label: _t("This Year") },
            { key: "last_12_months", label: _t("Last 12 Months") },
            { key: "all", label: _t("All Time") },
            { key: "custom", label: _t("Custom Range") },
        ];
    }

    applyPreset(preset) {
        const today = DateTime.local().startOf("day");
        let from = null;
        let to = today;
        switch (preset) {
            case "this_month":
                from = today.startOf("month");
                break;
            case "last_month":
                from = today.minus({ months: 1 }).startOf("month");
                to = from.endOf("month").startOf("day");
                break;
            case "this_quarter":
                from = today.startOf("quarter");
                break;
            case "this_year":
                from = today.startOf("year");
                break;
            case "last_12_months":
                from = today.minus({ months: 12 }).plus({ days: 1 });
                break;
            case "all":
                to = null;
                break;
            case "custom":
                return;
        }
        this.state.dateFrom = from ? serializeDate(from) : "";
        this.state.dateTo = to ? serializeDate(to) : "";
    }

    get filters() {
        const s = this.state;
        const filters = {};
        if (s.dateFrom) {
            filters.date_from = s.dateFrom;
        }
        if (s.dateTo) {
            filters.date_to = s.dateTo;
        }
        if (s.userId) {
            filters.user_ids = [parseInt(s.userId)];
        }
        if (s.teamId) {
            filters.team_ids = [parseInt(s.teamId)];
        }
        if (s.sourceId) {
            filters.source_ids = [parseInt(s.sourceId)];
        }
        if (s.companyId) {
            filters.company_ids = [parseInt(s.companyId)];
        }
        if (s.status) {
            filters.statuses = [s.status];
        }
        return filters;
    }

    isSelected(field, value) {
        return `${value}` === `${this.state[field]}`;
    }

    async loadData() {
        this.state.loading = true;
        this.state.data = await this.orm.call("crm.ss.dashboard", "get_dashboard_data", [this.filters]);
        this.state.loading = false;
    }

    onPresetChange(ev) {
        this.state.preset = ev.target.value;
        this.applyPreset(this.state.preset);
        if (this.state.preset !== "custom") {
            this.loadData();
        }
    }

    onDateChange(field, ev) {
        this.state[field] = ev.target.value;
        this.state.preset = "custom";
        this.loadData();
    }

    onSelectChange(field, ev) {
        this.state[field] = ev.target.value;
        this.loadData();
    }

    onResetFilters() {
        Object.assign(this.state, {
            preset: "this_year",
            userId: "",
            teamId: "",
            sourceId: "",
            status: "",
            companyId: "",
        });
        this.applyPreset("this_year");
        this.loadData();
    }

    get labels() {
        return {
            pipeline: _t("Opportunity Pipeline"),
            pipelineSub: _t("Open opportunities by stage (count)"),
            forecast: _t("Expected Revenue by Closing Month"),
            forecastSub: _t("Open pipeline forecast"),
            monthly: _t("Monthly Lead Creation & Conversion"),
            monthlySub: _t("Leads created vs converted per month"),
            trend: _t("Lead Conversion Trend"),
            trendSub: _t("Share of each month's leads converted"),
            bySource: _t("Leads by Source"),
            byUser: _t("Leads by Salesperson"),
            byStatus: _t("Leads by Status"),
            byRating: _t("Leads by Rating"),
            performance: _t("Salesperson Performance"),
            performanceSub: _t("Won revenue and open pipeline"),
            lost: _t("Lost Lead Analysis"),
            lostSub: _t("Lost leads and opportunities by reason"),
        };
    }

    // ------------------------------------------------------------------
    // Formatting
    // ------------------------------------------------------------------

    get currencyId() {
        return this.state.data?.currency_id || this.state.options?.currency_id;
    }

    money(value, humanReadable = true) {
        return formatCurrency(value || 0, this.currencyId, { humanReadable });
    }

    get kpiCards() {
        const k = this.state.data.kpis;
        return [
            { key: "total_leads", label: _t("Total Leads"), value: k.total_leads, icon: "person_add", color: "blue" },
            { key: "new_leads", label: _t("New Leads"), value: k.new_leads, icon: "add_circle", color: "sky" },
            { key: "qualified_leads", label: _t("Qualified Leads"), value: k.qualified_leads, icon: "verified", color: "green" },
            { key: "converted_leads", label: _t("Converted Leads"), value: k.converted_leads, icon: "swap_horiz", color: "teal" },
            { key: "lost_leads", label: _t("Lost Leads"), value: k.lost_leads, icon: "cancel", color: "red" },
            { key: "opportunities", label: _t("Opportunities"), value: k.opportunities, icon: "handshake", color: "purple" },
            { key: "converted_leads", label: _t("Lead Conversion Rate"), value: `${k.conversion_rate}%`, icon: "percent", color: "orange", sub: _t("converted / total leads") },
            { key: "open_pipeline", label: _t("Expected Revenue"), value: this.money(k.expected_revenue), icon: "payments", color: "navy", sub: _t("Weighted: %s", this.money(k.weighted_revenue)) },
        ];
    }

    get secondaryKpis() {
        const k = this.state.data.kpis;
        return [
            { key: "won", label: _t("Won Revenue"), value: this.money(k.won_revenue) },
            { key: "won", label: _t("Won Deals"), value: k.won_count },
            { key: "won", label: _t("Win Rate"), value: `${k.win_rate}%` },
            { key: "hot_leads", label: _t("Hot Leads"), value: k.hot_leads },
            { key: "working_leads", label: _t("Working Leads"), value: k.working_leads },
            { key: "total_leads", label: _t("Avg. Lead Score"), value: k.avg_score },
        ];
    }

    // ------------------------------------------------------------------
    // Charts
    // ------------------------------------------------------------------

    get charts() {
        return toRaw(this.state.data).charts;
    }

    baseBarOptions({ horizontal = false, money = false, stacked = false } = {}) {
        const valueAxis = {
            beginAtZero: true,
            stacked,
            grid: { color: "rgba(0,0,0,0.06)" },
            ticks: money ? { callback: (v) => this.money(v) } : { precision: 0 },
        };
        const categoryAxis = { stacked, grid: { display: false }, ticks: { autoSkip: false, maxRotation: 45 } };
        return {
            indexAxis: horizontal ? "y" : "x",
            plugins: {
                legend: { display: stacked, position: "bottom" },
                tooltip: money ? { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${this.money(ctx.raw, false)}` } } : {},
            },
            scales: horizontal ? { x: valueAxis, y: categoryAxis } : { x: categoryAxis, y: valueAxis },
        };
    }

    get leadsBySourceConfig() {
        const rows = this.charts.leads_by_source;
        return {
            type: "bar",
            data: {
                labels: rows.map((r) => r.label),
                datasets: [{ label: _t("Leads"), data: rows.map((r) => r.values[0]), backgroundColor: SS_COLORS[0], borderRadius: 4 }],
            },
            options: this.baseBarOptions({ horizontal: true }),
        };
    }

    get leadsByUserConfig() {
        const rows = this.charts.leads_by_user;
        return {
            type: "bar",
            data: {
                labels: rows.map((r) => r.label),
                datasets: [{ label: _t("Leads"), data: rows.map((r) => r.values[0]), backgroundColor: SS_COLORS[1], borderRadius: 4 }],
            },
            options: this.baseBarOptions({ horizontal: true }),
        };
    }

    get leadsByStatusConfig() {
        const rows = this.charts.leads_by_status;
        return {
            type: "doughnut",
            data: {
                labels: rows.map((r) => r.label),
                datasets: [{
                    data: rows.map((r) => r.values[0]),
                    backgroundColor: rows.map((r) => STATUS_COLORS[r.id] || SS_COLORS[0]),
                    borderWidth: 2,
                }],
            },
            options: { cutout: "62%", plugins: { legend: { position: "right" } } },
        };
    }

    get leadsByRatingConfig() {
        const rows = this.charts.leads_by_rating;
        return {
            type: "doughnut",
            data: {
                labels: rows.map((r) => r.label),
                datasets: [{
                    data: rows.map((r) => r.values[0]),
                    backgroundColor: rows.map((r) => RATING_COLORS[r.id] || SS_COLORS[0]),
                    borderWidth: 2,
                }],
            },
            options: { cutout: "62%", plugins: { legend: { position: "right" } } },
        };
    }

    get pipelineConfig() {
        const rows = this.charts.pipeline_by_stage;
        return {
            type: "bar",
            data: {
                labels: rows.map((r) => `${r.label} (${r.values[0]})`),
                datasets: [
                    { label: _t("Expected Revenue"), data: rows.map((r) => r.values[1]), backgroundColor: SS_COLORS[0], borderRadius: 4 },
                    { label: _t("Weighted Revenue"), data: rows.map((r) => r.values[2]), backgroundColor: SS_COLORS[1], borderRadius: 4 },
                ],
            },
            options: Object.assign(this.baseBarOptions({ money: true }), {
                plugins: {
                    legend: { display: true, position: "bottom" },
                    tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${this.money(ctx.raw, false)}` } },
                },
            }),
        };
    }

    get monthlyConfig() {
        const rows = this.charts.monthly;
        return {
            type: "bar",
            data: {
                labels: rows.map((r) => r.label),
                datasets: [
                    { type: "bar", label: _t("Leads Created"), data: rows.map((r) => r.created), backgroundColor: SS_COLORS[0], borderRadius: 4, yAxisID: "y" },
                    { type: "bar", label: _t("Leads Converted"), data: rows.map((r) => r.converted), backgroundColor: SS_COLORS[4], borderRadius: 4, yAxisID: "y" },
                ],
            },
            options: {
                plugins: { legend: { position: "bottom" } },
                scales: {
                    x: { grid: { display: false } },
                    y: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: "rgba(0,0,0,0.06)" } },
                },
            },
        };
    }

    get conversionTrendConfig() {
        const rows = this.charts.monthly;
        return {
            type: "line",
            data: {
                labels: rows.map((r) => r.label),
                datasets: [{
                    label: _t("Conversion Rate (%)"),
                    data: rows.map((r) => r.conversion_rate),
                    borderColor: SS_COLORS[3],
                    backgroundColor: "rgba(186, 1, 255, 0.12)",
                    fill: true,
                    tension: 0.35,
                    pointRadius: 3,
                }],
            },
            options: {
                plugins: { legend: { display: false } },
                scales: {
                    x: { grid: { display: false } },
                    y: { beginAtZero: true, suggestedMax: 100, ticks: { callback: (v) => `${v}%` }, grid: { color: "rgba(0,0,0,0.06)" } },
                },
            },
        };
    }

    get forecastConfig() {
        const rows = this.charts.revenue_forecast;
        return {
            type: "bar",
            data: {
                labels: rows.map((r) => r.label),
                datasets: [
                    { label: _t("Expected"), data: rows.map((r) => r.expected), backgroundColor: SS_COLORS[6], borderRadius: 4 },
                    { label: _t("Weighted"), data: rows.map((r) => r.weighted), backgroundColor: SS_COLORS[2], borderRadius: 4 },
                ],
            },
            options: Object.assign(this.baseBarOptions({ money: true }), {
                plugins: {
                    legend: { display: true, position: "bottom" },
                    tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${this.money(ctx.raw, false)}` } },
                },
            }),
        };
    }

    get lostReasonsConfig() {
        const rows = this.charts.lost_reasons;
        return {
            type: "bar",
            data: {
                labels: rows.map((r) => r.label),
                datasets: [{ label: _t("Lost"), data: rows.map((r) => r.values[0]), backgroundColor: SS_COLORS[5], borderRadius: 4 }],
            },
            options: this.baseBarOptions({ horizontal: true }),
        };
    }

    get performanceConfig() {
        const rows = this.state.data.leaderboard.slice(0, 10);
        return {
            type: "bar",
            data: {
                labels: rows.map((r) => r.name),
                datasets: [
                    { label: _t("Won Revenue"), data: rows.map((r) => r.won_revenue), backgroundColor: SS_COLORS[4], borderRadius: 4 },
                    { label: _t("Open Pipeline"), data: rows.map((r) => r.pipeline), backgroundColor: SS_COLORS[0], borderRadius: 4 },
                ],
            },
            options: Object.assign(this.baseBarOptions({ money: true }), {
                plugins: {
                    legend: { display: true, position: "bottom" },
                    tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${this.money(ctx.raw, false)}` } },
                },
            }),
        };
    }

    // ------------------------------------------------------------------
    // Drill-down
    // ------------------------------------------------------------------

    async openDrilldown(metric, groupField = null, groupValue = null) {
        const action = await this.orm.call("crm.ss.dashboard", "get_drilldown_action", [metric, this.filters, groupField, groupValue]);
        await this.action.doAction(action);
    }

    onKpiClick(card) {
        return this.openDrilldown(card.key);
    }

    drill(chartKey, metric, groupField) {
        return (index) => {
            const row = this.charts[chartKey][index];
            if (row) {
                this.openDrilldown(metric, groupField, row.id);
            }
        };
    }

    onLeaderClick(row) {
        return this.openDrilldown("total_leads", "user_id", row.id);
    }
}

registry.category("actions").add("crm_ss_dashboard", SsCrmDashboard);
