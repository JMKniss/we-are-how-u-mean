"""
Optional shared-password gate.

Off unless APP_PASSWORD is set in the environment, so the same code serves a
public site and a private one and the choice is made in Render's dashboard
rather than in a commit. Nothing secret is ever stored in the repo.

This is a garden gate, not a lock. One password shared among ten people, no
per-person identity, no audit trail. It is the right weight for keeping a
fantasy league's scores off the open web and the wrong weight for anything
that actually matters.
"""
import hmac
import os

import streamlit as st

_OK = "_password_ok"


def require_password() -> None:
    """Show a password prompt and halt the script until it is answered."""
    expected = os.getenv("APP_PASSWORD")
    if not expected:
        return                       # unset: the site is public
    if st.session_state.get(_OK):
        return

    st.title("🏈 We Are How U Mean")
    st.caption("League members only. Ask the commissioner for the password.")

    with st.form("login"):
        supplied = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Enter")

    if submitted:
        # compare_digest rather than ==, so a wrong guess takes the same time
        # to reject whatever it got right.
        if hmac.compare_digest(supplied, expected):
            st.session_state[_OK] = True
            st.rerun()
        else:
            st.error("Wrong password.")

    st.stop()
