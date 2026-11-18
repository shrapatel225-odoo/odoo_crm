import { Component, t, useProps } from "@odoo/owl";
import { useChart } from "@web/core/utils/chart_hook";

/**
 * Small Chart.js wrapper (Chart.js bundle is lazy loaded by useChart).
 */
export class SsChartCard extends Component {
    static template = "crm_smart_sales.ChartCard";

    props = useProps({
        title: t.string(),
        subtitle: t.string().optional(),
        config: t.object(),
        onPointClick: t.function().optional(),
        empty: t.boolean().optional(),
        height: t.number().optional(),
    });

    chart = useChart(() => this.getConfig());

    getConfig() {
        const config = this.props.config;
        const onPointClick = this.props.onPointClick;
        const options = Object.assign(
            {
                responsive: true,
                maintainAspectRatio: false,
                animation: { duration: 300 },
            },
            config.options || {}
        );
        if (onPointClick) {
            options.onClick = (event, elements) => {
                if (elements && elements.length) {
                    onPointClick(elements[0].index, elements[0].datasetIndex);
                }
            };
            options.onHover = (event, elements) => {
                event.native.target.style.cursor = elements && elements.length ? "pointer" : "default";
            };
        }
        return {
            type: config.type,
            data: config.data,
            options,
        };
    }
}
