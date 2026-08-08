"""
ui_render.py — BoomCast UI render helpers (Phase 4).

Extracted from app.py (mlb-hr-and-k v46.54). UNLIKE scoring/utils/helpers, these
touch Streamlit (st.*) — they render UI. They compile and import cleanly, but
pixel-identical rendering can only be confirmed by running BoomCast live (mocking
st can't verify visual output). Behavior is intended identical to the original.

These are self-contained: they take scalars/DataFrames and render, with no
dependency on app.py's module-level globals.
"""
import math
import pandas as pd
import streamlit as st
try:
    import streamlit.components.v1 as _components
except Exception:  # pragma: no cover
    _components = None


# ────────────────────────────────────────────────────────────────────────────
def _section_banner(title, sub=""):
    """v45.34: scoreboard-style section banner — amber rail, Oswald caps.
    Replaces plain subheaders on major sections for the ballpark feel."""
    _s = f'<div class="lc-sub">{sub}</div>' if sub else ""
    st.markdown(
        f'<div class="lc-banner"><div class="lc-title">{title}</div>{_s}</div>',
        unsafe_allow_html=True,
    )

# ────────────────────────────────────────────────────────────────────────────
def _player_col(label="Player", **kw):
    """v45.18 (UI): TextColumn for the player-name column, PINNED to the left
    so it stays visible while wide tables scroll horizontally (the single
    biggest mobile readability win). `pinned` is a newer Streamlit
    column_config parameter — fall back to unpinned on older versions
    instead of crashing."""
    try:
        return st.column_config.TextColumn(label, pinned=True, **kw)
    except TypeError:
        return st.column_config.TextColumn(label, **kw)

# ────────────────────────────────────────────────────────────────────────────
def _render_wind_diagram(wind_mph, wind_dir_deg, cf_bearing, venue_name=None):
    """Draw an SVG baseball-field wind diagram.

    wind_dir_deg = compass direction wind is COMING FROM (meteorological)
    cf_bearing   = compass direction of CF from home plate (so 0 = CF points
                   due North, 22 = Yankee Stadium CF points ~NNE)

    Wind angle relative to CF:
      0   = wind blowing OUT toward CF (tailwind, HR-friendly)
      180 = wind blowing IN from CF (headwind, HR-suppressing)
      90  = crosswind L→R
      270 = crosswind R→L
    """
    if wind_mph is None or wind_dir_deg is None:
        return
    try:
        wind_mph = float(wind_mph)
        wind_dir_deg = float(wind_dir_deg)
    except (TypeError, ValueError):
        return
    if wind_mph < 1:
        return  # negligible wind — skip viz entirely
    cf_bearing = float(cf_bearing or 0)

    # Wind blows TOWARD = (wind_dir + 180) mod 360
    # Angle relative to CF axis: 0 = straight out, 180 = straight in
    blow_to = (wind_dir_deg + 180) % 360
    angle_rel_cf = (blow_to - cf_bearing) % 360
    # Normalize to -180..180 for math
    if angle_rel_cf > 180:
        angle_rel_cf -= 360

    abs_angle = abs(angle_rel_cf)
    # HR impact classification
    if abs_angle <= 45:
        color = "#22c55e"  # green — blowing out
        impact = "OUT to OF"
        impact_short = "tailwind"
    elif abs_angle >= 135:
        color = "#ef4444"  # red — blowing in
        impact = "IN from OF"
        impact_short = "headwind"
    else:
        color = "#eab308"  # yellow — crosswind
        impact = "across field"
        impact_short = "crosswind"

    # Specifically helpful for LHB / RHB.
    # v44.97 (review): positive angle_rel_cf = clockwise from CF = toward RF
    # (matches SVG rot, positive=clockwise=RF/1B side). RF is the LHB pull side;
    # LF is the RHB pull side. The labels were previously swapped, contradicting
    # the arrow. Corrected below.
    pull_side = ""
    if 30 <= angle_rel_cf <= 75:        # blowing toward RF (LHB pull side)
        pull_side = " → boosts LHB pull (RF)"
    elif -75 <= angle_rel_cf <= -30:    # blowing toward LF (RHB pull side)
        pull_side = " → boosts RHB pull (LF)"
    elif 105 <= abs_angle <= 150 and angle_rel_cf < 0:
        pull_side = " ← from LF (hurts RHB pull)"
    elif 105 <= abs_angle <= 150 and angle_rel_cf > 0:
        pull_side = " ← from RF (hurts LHB pull)"

    # SVG: 200x200, home plate at bottom center, CF arrow pointing up
    # The arrow inside the field shows wind direction relative to the
    # field as seen from above (CF at top, home plate at bottom).
    # Arrow ROTATES based on angle_rel_cf — 0 = pointing toward CF (up).
    # v43.82 cleanup: `import math` here was dead (no math.* call follows).
    # SVG rotation: 0 = up (toward CF). Positive rotation = clockwise
    # (toward RF / 1B side). angle_rel_cf positive means wind is east of
    # CF axis (toward LF if positive bearing rotation).
    # Wait — when looking FROM home plate TO CF (overhead view, CF up):
    #   positive angle_rel_cf = wind blowing-toward direction is rotated
    #   clockwise from CF. We need to draw arrow at that rotation.
    rot = angle_rel_cf  # SVG rotate uses degrees, positive = clockwise

    # Arrow path (a centered arrow pointing UP)
    # Tail at (100, 145), head at (100, 55), arrowhead at (90,75)-(110,75)
    cx, cy = 100, 100
    svg = f'''
<svg viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg" style="background:#0d1117; border-radius:8px;">
  <!-- Outfield grass arc -->
  <path d="M 30 130 A 70 70 0 0 1 170 130 L 100 195 Z" fill="#1a3a1a" stroke="#2d5a2d" stroke-width="1"/>
  <!-- Infield diamond (rotated 45deg) -->
  <polygon points="100,130 130,160 100,190 70,160" fill="#3a2a1a" stroke="#5a4a2a" stroke-width="1.5"/>
  <!-- Bases -->
  <circle cx="100" cy="190" r="3" fill="#ffffff"/>
  <circle cx="130" cy="160" r="3" fill="#ffffff"/>
  <circle cx="100" cy="130" r="3" fill="#ffffff"/>
  <circle cx="70" cy="160" r="3" fill="#ffffff"/>
  <!-- CF / LF / RF labels -->
  <text x="100" y="25" text-anchor="middle" font-size="11" fill="#888" font-family="sans-serif">CF</text>
  <text x="25" y="120" text-anchor="middle" font-size="11" fill="#888" font-family="sans-serif">LF</text>
  <text x="175" y="120" text-anchor="middle" font-size="11" fill="#888" font-family="sans-serif">RF</text>
  <text x="100" y="200" text-anchor="middle" font-size="9" fill="#666" font-family="sans-serif">HP</text>
  <!-- Wind arrow (rotates around center) -->
  <g transform="translate({cx},{cy}) rotate({rot:.1f})">
    <line x1="0" y1="50" x2="0" y2="-50" stroke="{color}" stroke-width="4" stroke-linecap="round"/>
    <polygon points="0,-60 -10,-40 10,-40" fill="{color}"/>
    <circle cx="0" cy="50" r="4" fill="{color}"/>
  </g>
  <!-- Wind speed text -->
  <text x="100" y="105" text-anchor="middle" font-size="14" fill="#ffffff" font-weight="bold" font-family="sans-serif">{wind_mph:.0f}mph</text>
</svg>
'''
    # Display with caption
    col_a, col_b = st.columns([1, 2])
    with col_a:
        # v43.62 (reviewer suggestion): Streamlit's markdown sanitizer can
        # strip inline <svg> even with unsafe_allow_html=True, especially
        # after Streamlit updates. components.v1.html renders raw HTML in
        # a sandbox iframe — bypasses the sanitizer entirely. Fall back to
        # st.markdown if components is unavailable for any reason.
        try:
            import streamlit.components.v1 as _components
            _components.html(svg, height=210)
        except Exception:
            st.markdown(svg, unsafe_allow_html=True)
    with col_b:
        st.markdown(
            f"**Wind: {wind_mph:.0f} mph blowing {impact}**  \n"
            f"<span style='color:{color}'>● {impact_short}</span>"
            f"{pull_side}  \n"
            f"<small>Coming from {wind_dir_deg:.0f}° (compass) · "
            f"CF bearing {cf_bearing:.0f}°</small>",
            unsafe_allow_html=True,
        )
