"""
Structured intake form component for the BlogGit frontend.

Renders a Streamlit form with checkboxes (multi-select), radio buttons
(single-select), and text inputs (custom additions / free-text) for each
intake question defined in ``app.agent.intake_questions``.

On submit, returns a ``[intake_form_v1]``-prefixed batch string ready to send
to the backend. Returns ``None`` when the form has not been submitted.
"""

from __future__ import annotations

import streamlit as st

from app.agent.intake_questions import (
    INTAKE_QUESTION_SPECS,
    format_batch_answers,
)


def render_intake_form() -> str | None:
    """Render the structured intake form.

    Returns the formatted batch string when the user submits, otherwise ``None``.
    """
    st.markdown("### Blog post preferences")
    st.caption(
        "Choose from the predefined options for each question. "
        "Add any extra instructions in the text fields below each section."
    )

    with st.form("intake_form", border=True):
        collected: dict[str, str] = {}

        for spec in INTAKE_QUESTION_SPECS:
            st.markdown(f"**{spec.question}**")

            selected_values: list[str] = []

            if not spec.options:
                # Free-text only question (e.g. extra_instructions)
                text_val = st.text_area(
                    spec.custom_label,
                    key=f"intake_{spec.key}_text",
                    height=80,
                    label_visibility="visible",
                )
                collected[spec.key] = text_val.strip()

            elif spec.multi_select:
                # Checkboxes for multi-select + optional free-text
                cols = st.columns(2)
                for idx, option in enumerate(spec.options):
                    col = cols[idx % 2]
                    if col.checkbox(option.label, key=f"intake_{spec.key}_{idx}"):
                        selected_values.append(option.value)

                custom_val = st.text_input(
                    spec.custom_label,
                    key=f"intake_{spec.key}_custom",
                    label_visibility="visible",
                )
                if custom_val.strip():
                    selected_values.append(custom_val.strip())

                collected[spec.key] = ", ".join(selected_values)

            else:
                # Radio buttons for single-select + optional free-text
                option_labels = [o.label for o in spec.options]
                chosen_label = st.radio(
                    spec.question,
                    options=option_labels,
                    key=f"intake_{spec.key}_radio",
                    label_visibility="collapsed",
                )
                chosen_value = next(
                    (o.value for o in spec.options if o.label == chosen_label),
                    chosen_label or "",
                )
                selected_values.append(chosen_value)

                custom_val = st.text_input(
                    spec.custom_label,
                    key=f"intake_{spec.key}_custom",
                    label_visibility="visible",
                )
                if custom_val.strip():
                    selected_values.append(custom_val.strip())

                collected[spec.key] = ", ".join(v for v in selected_values if v)

            st.markdown("")  # visual spacer between questions

        submitted = st.form_submit_button("Submit preferences", type="primary")

    if submitted:
        return format_batch_answers(collected)

    return None
