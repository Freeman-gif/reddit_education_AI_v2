"""Page layouts for the Dash dashboard."""

import dash_bootstrap_components as dbc
from dash import dcc, html, dash_table


def make_header(stats: dict) -> dbc.Row:
    """Dashboard header with summary stats."""
    cards = [
        ("Relevant Posts", stats.get("total_posts", 0)),
        ("Comments", stats.get("total_comments", 0)),
        ("L1 Topics", stats.get("topics_l1", 0)),
        ("L2 Topics", stats.get("topics_l2", 0)),
        ("Subreddits", stats.get("subreddits", 0)),
    ]
    return dbc.Row([
        dbc.Col(dbc.Card(dbc.CardBody([
            html.H4(str(val), className="card-title text-center mb-0"),
            html.P(label, className="card-text text-center text-muted"),
        ]), className="shadow-sm"), width=True)
        for label, val in cards
    ], className="mb-4 g-3")


def make_semantic_map_tab() -> dbc.Tab:
    """Tab 1: 2D UMAP scatter plot."""
    return dbc.Tab(label="Semantic Map", children=[
        dbc.Row([
            dbc.Col([
                html.Label("Color by:"),
                dcc.RadioItems(
                    id="map-color-by",
                    options=[
                        {"label": "L1 Topic", "value": "l1_label"},
                        {"label": "L2 Topic", "value": "l2_label"},
                        {"label": "Category", "value": "category"},
                        {"label": "Subreddit", "value": "subreddit"},
                    ],
                    value="l1_label",
                    inline=True,
                ),
            ], width=8),
            dbc.Col([
                html.Label("Point size:"),
                dcc.Slider(id="map-point-size", min=2, max=12, value=5, step=1,
                           marks={2: "2", 5: "5", 8: "8", 12: "12"}),
            ], width=4),
        ], className="mb-3 mt-3"),
        dcc.Graph(id="semantic-map", style={"height": "700px"}),
        html.Div(id="map-click-info", className="mt-3"),
    ])


def make_timeline_tab() -> dbc.Tab:
    """Tab 2: Topic frequency over time."""
    return dbc.Tab(label="Timeline", children=[
        dbc.Row([
            dbc.Col([
                html.Label("Topic level:"),
                dcc.RadioItems(
                    id="timeline-level",
                    options=[
                        {"label": "L1 (Broad)", "value": "l1"},
                        {"label": "Leaf Topics", "value": "leaf"},
                    ],
                    value="l1",
                    inline=True,
                ),
            ], width=6),
            dbc.Col([
                html.Label("Chart type:"),
                dcc.RadioItems(
                    id="timeline-chart-type",
                    options=[
                        {"label": "Stacked Area", "value": "area"},
                        {"label": "Line", "value": "line"},
                    ],
                    value="area",
                    inline=True,
                ),
            ], width=6),
        ], className="mb-3 mt-3"),
        dcc.Graph(id="timeline-chart", style={"height": "600px"}),
    ])


def make_emotion_tab() -> dbc.Tab:
    """Tab 3: Emotion heatmap + stance bars."""
    return dbc.Tab(label="Emotion Heatmap", children=[
        dbc.Row([
            dbc.Col([
                html.Label("Topic level:"),
                dcc.RadioItems(
                    id="emotion-level",
                    options=[
                        {"label": "L1 (Broad)", "value": 1},
                        {"label": "L2 (Niche)", "value": 2},
                    ],
                    value=2,
                    inline=True,
                ),
            ], width=6),
            dbc.Col([
                html.Label("Min comments:"),
                dcc.Slider(id="emotion-min-comments", min=0, max=50, value=5, step=5,
                           marks={0: "0", 10: "10", 25: "25", 50: "50"}),
            ], width=6),
        ], className="mb-3 mt-3"),
        dbc.Row([
            dbc.Col(dcc.Graph(id="emotion-heatmap", style={"height": "600px"}), width=8),
            dbc.Col(dcc.Graph(id="stance-bars", style={"height": "600px"}), width=4),
        ]),
    ])


def make_explorer_tab() -> dbc.Tab:
    """Tab 4: Searchable/filterable post table."""
    return dbc.Tab(label="Explorer", children=[
        dbc.Row([
            dbc.Col([
                dbc.Input(id="explorer-search", placeholder="Search posts...",
                          type="text", debounce=True),
            ], width=4),
            dbc.Col([
                dcc.Dropdown(id="explorer-category", placeholder="Filter by category",
                             clearable=True),
            ], width=3),
            dbc.Col([
                dcc.Dropdown(id="explorer-topic", placeholder="Filter by L1 topic",
                             clearable=True),
            ], width=3),
            dbc.Col([
                dbc.Button("Search", id="explorer-btn", color="primary", className="w-100"),
            ], width=2),
        ], className="mb-3 mt-3"),
        dash_table.DataTable(
            id="explorer-table",
            columns=[
                {"name": "Title", "id": "title"},
                {"name": "Subreddit", "id": "subreddit"},
                {"name": "Category", "id": "category"},
                {"name": "L1 Topic", "id": "l1_label"},
                {"name": "Score", "id": "score"},
                {"name": "Comments", "id": "num_comments"},
            ],
            style_table={"overflowX": "auto"},
            style_cell={"textAlign": "left", "padding": "8px",
                        "maxWidth": "400px", "overflow": "hidden",
                        "textOverflow": "ellipsis"},
            style_header={"fontWeight": "bold", "backgroundColor": "#f8f9fa"},
            row_selectable="single",
            page_size=20,
            sort_action="native",
            filter_action="native",
        ),
        html.Div(id="explorer-detail", className="mt-4"),
    ])


def make_layout(stats: dict) -> html.Div:
    """Build the full dashboard layout."""
    return html.Div([
        dbc.Container([
            html.H2("AI in K-12 Education: Reddit Analysis Dashboard",
                     className="text-center mt-3 mb-3"),
            make_header(stats),
            dbc.Tabs([
                make_semantic_map_tab(),
                make_timeline_tab(),
                make_emotion_tab(),
                make_explorer_tab(),
            ], className="mb-4"),
        ], fluid=True),
    ])
