"""Dash callbacks for interactivity."""

import json
from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Input, Output, State, callback, html, no_update
import dash_bootstrap_components as dbc

from dashboard.data_loader import (
    get_semantic_map_data, get_topics, get_topics_over_time,
    get_emotion_heatmap_data, get_explorer_data, get_post_comments,
)


def register_callbacks(app):
    """Register all callbacks with the Dash app."""

    # ── Tab 1: Semantic Map ──────────────────────────────────────────────
    @app.callback(
        Output("semantic-map", "figure"),
        [Input("map-color-by", "value"),
         Input("map-point-size", "value")],
    )
    def update_semantic_map(color_by, point_size):
        df = get_semantic_map_data()
        if df.empty:
            return go.Figure().add_annotation(text="No data available", showarrow=False)

        fig = px.scatter(
            df, x="umap_x", y="umap_y", color=color_by,
            hover_data=["title", "subreddit", "score", "category"],
            custom_data=["post_id"],
            title="Semantic Map of Reddit Posts",
        )
        fig.update_traces(marker=dict(size=point_size, opacity=0.7))
        fig.update_layout(
            xaxis_title="UMAP-1", yaxis_title="UMAP-2",
            legend_title=color_by.replace("_", " ").title(),
            template="plotly_white",
        )
        return fig

    @app.callback(
        Output("map-click-info", "children"),
        Input("semantic-map", "clickData"),
    )
    def show_map_click(click_data):
        if not click_data:
            return no_update
        point = click_data["points"][0]
        post_id = point.get("customdata", [None])[0]
        if not post_id:
            return no_update
        df = get_explorer_data(search=None, category=None, limit=1000)
        row = df[df["id"] == post_id]
        if row.empty:
            return html.P(f"Post {post_id} not found")
        r = row.iloc[0]
        return dbc.Card(dbc.CardBody([
            html.H5(r["title"]),
            html.P([
                dbc.Badge(r["subreddit"], color="primary", className="me-2"),
                dbc.Badge(r["category"] or "", color="secondary", className="me-2"),
                f"Score: {r['score']} | Comments: {r['num_comments']}",
            ]),
            html.P(r.get("summary", ""), className="text-muted"),
        ]), className="shadow-sm")

    # ── Tab 2: Timeline ──────────────────────────────────────────────────
    @app.callback(
        Output("timeline-chart", "figure"),
        [Input("timeline-level", "value"),
         Input("timeline-chart-type", "value")],
    )
    def update_timeline(level, chart_type):
        df = get_topics_over_time()
        if df.empty:
            return go.Figure().add_annotation(text="No temporal data available", showarrow=False)

        if chart_type == "area":
            fig = px.area(df, x="time_bin", y="frequency", color="label",
                          title="Topic Frequency Over Time")
        else:
            fig = px.line(df, x="time_bin", y="frequency", color="label",
                          title="Topic Frequency Over Time")

        fig.update_layout(
            xaxis_title="Time", yaxis_title="Frequency",
            legend_title="Topic", template="plotly_white",
        )
        return fig

    # ── Tab 3: Emotion Heatmap ───────────────────────────────────────────
    @app.callback(
        [Output("emotion-heatmap", "figure"),
         Output("stance-bars", "figure")],
        [Input("emotion-level", "value"),
         Input("emotion-min-comments", "value")],
    )
    def update_emotion_heatmap(level, min_comments):
        df = get_emotion_heatmap_data()
        if df.empty:
            empty = go.Figure().add_annotation(text="No emotion data", showarrow=False)
            return empty, empty

        df = df[(df["level"] == level) & (df["num_comments"] >= min_comments)]
        if df.empty:
            empty = go.Figure().add_annotation(text="No data for filters", showarrow=False)
            return empty, empty

        # Parse emotion distributions
        all_emotions = set()
        parsed = []
        for _, row in df.iterrows():
            emo = json.loads(row["emotion_distribution"]) if row["emotion_distribution"] else {}
            all_emotions.update(emo.keys())
            parsed.append(emo)

        emotions_list = sorted(all_emotions)
        labels = df["label"].tolist()

        # Build heatmap matrix
        z = []
        for emo_dict in parsed:
            z.append([emo_dict.get(e, 0) for e in emotions_list])

        heatmap = go.Figure(data=go.Heatmap(
            z=z, x=emotions_list, y=labels,
            colorscale="YlOrRd", hoverongaps=False,
        ))
        heatmap.update_layout(
            title="Emotion Intensity by Topic",
            xaxis_title="Emotion", yaxis_title="Topic",
            template="plotly_white",
            yaxis=dict(autorange="reversed"),
        )

        # Stance bar chart
        stance_fig = go.Figure()
        stance_fig.add_trace(go.Bar(
            y=labels, x=df["agree_pct"], name="Agree",
            orientation="h", marker_color="#2ecc71",
        ))
        stance_fig.add_trace(go.Bar(
            y=labels, x=df["disagree_pct"], name="Disagree",
            orientation="h", marker_color="#e74c3c",
        ))
        stance_fig.add_trace(go.Bar(
            y=labels, x=df["neutral_pct"], name="Neutral",
            orientation="h", marker_color="#95a5a6",
        ))
        stance_fig.update_layout(
            barmode="stack", title="Stance Distribution",
            xaxis_title="Percentage", template="plotly_white",
            yaxis=dict(autorange="reversed"),
        )

        return heatmap, stance_fig

    # ── Tab 4: Explorer ──────────────────────────────────────────────────
    @app.callback(
        [Output("explorer-category", "options"),
         Output("explorer-topic", "options")],
        Input("explorer-btn", "n_clicks"),  # trigger on load
    )
    def populate_filters(_):
        topics = get_topics(level=1)
        categories = get_explorer_data(limit=10000)["category"].dropna().unique()
        cat_options = [{"label": c, "value": c} for c in sorted(categories)]
        topic_options = [
            {"label": r["llm_label"] or r["auto_label"] or f"Topic {r['topic_id']}",
             "value": r["topic_id"]}
            for _, r in topics.iterrows()
        ]
        return cat_options, topic_options

    @app.callback(
        Output("explorer-table", "data"),
        [Input("explorer-btn", "n_clicks"),
         Input("explorer-search", "value"),
         Input("explorer-category", "value"),
         Input("explorer-topic", "value")],
    )
    def update_explorer(_, search, category, topic_id):
        df = get_explorer_data(
            topic_id=topic_id, search=search, category=category, limit=200
        )
        if df.empty:
            return []
        df["l1_label"] = df["l1_label"].fillna("")
        return df[["id", "title", "subreddit", "category", "l1_label",
                    "score", "num_comments"]].to_dict("records")

    @app.callback(
        Output("explorer-detail", "children"),
        Input("explorer-table", "selected_rows"),
        State("explorer-table", "data"),
    )
    def show_post_detail(selected_rows, data):
        if not selected_rows or not data:
            return no_update
        row = data[selected_rows[0]]
        post_id = row["id"]

        # Get full post data
        posts_df = get_explorer_data(search=None, category=None, limit=10000)
        post = posts_df[posts_df["id"] == post_id]
        if post.empty:
            return html.P("Post not found")
        post = post.iloc[0]

        # Get comments
        comments_df = get_post_comments(post_id)

        comment_cards = []
        for _, c in comments_df.iterrows():
            indent = c.get("depth", 0) * 20
            emotion_badge = ""
            if c.get("dominant_emotion"):
                sentiment_color = {"positive": "success", "negative": "danger",
                                   "neutral": "secondary"}.get(c.get("sentiment", ""), "info")
                emotion_badge = dbc.Badge(
                    f"{c['dominant_emotion']} ({c.get('sentiment', '')})",
                    color=sentiment_color, className="ms-2"
                )
            stance_badge = ""
            if c.get("stance"):
                stance_color = {"agree": "success", "disagree": "danger",
                                "neutral": "secondary"}.get(c["stance"], "info")
                stance_badge = dbc.Badge(c["stance"], color=stance_color, className="ms-2")

            comment_cards.append(html.Div([
                html.Div([
                    html.Strong(c.get("author", "[deleted]")),
                    html.Small(f" | score: {c.get('score', 0)}", className="text-muted"),
                    emotion_badge,
                    stance_badge,
                ]),
                html.P(c.get("body", "")[:500], className="mb-1"),
                html.Hr(),
            ], style={"marginLeft": f"{indent}px", "marginBottom": "4px"}))

        return dbc.Card(dbc.CardBody([
            html.H5(post["title"]),
            html.P([
                dbc.Badge(post.get("subreddit", ""), color="primary", className="me-2"),
                dbc.Badge(post.get("category", ""), color="secondary", className="me-2"),
                dbc.Badge(post.get("l1_label", ""), color="info", className="me-2"),
            ]),
            html.P(post.get("summary", ""), className="text-muted"),
            html.Hr(),
            html.H6(f"Comments ({len(comments_df)})"),
            html.Div(comment_cards) if comment_cards else html.P("No comments collected"),
        ]), className="shadow-sm")
