import streamlit as st
import os
import pandas as pd
from dotenv import load_dotenv, set_key
from scrapers import scrape_canvas, scrape_django, scrape_generic

load_dotenv()

st.set_page_config(page_title="Student Brain", page_icon="🧠", layout="wide")

DB_PATH     = "./chroma_db"
COURSES_DIR = "./Courses"
ENV_FILE    = ".env"


# ── Session state ──────────────────────────────────────────────────────────────
def _chunk_count() -> int:
    try:
        import chromadb
        return chromadb.PersistentClient(path=DB_PATH)\
                       .get_or_create_collection("student_brain").count()
    except Exception:
        return 0

def _has_courses() -> bool:
    return os.path.isdir(COURSES_DIR) and any(
        f for _, _, fs in os.walk(COURSES_DIR) for f in fs
    )

def _new_files_badge() -> int:
    try:
        from brain.ingest import new_files_since_last_index
        return len(new_files_since_last_index(COURSES_DIR, DB_PATH))
    except Exception:
        return 0

defaults = {
    "step":          0,
    "sites": [{
        "id": "canvas", "name": "Canvas — Rady MSBA", "type": "canvas",
        "url": "https://rady.instructure.com/",
        "token": os.getenv("CANVAS_ACCESS_TOKEN", ""), "selected": True,
    }],
    "scrape_done":   _has_courses(),
    "index_done":    _chunk_count() > 0,
    "openai_key":    os.getenv("OPENAI_API_KEY", ""),
    "anthropic_key": os.getenv("ANTHROPIC_API_KEY", ""),
    "model":         "claude-sonnet-4-6",
    "top_k":         8,
    "messages":      [],
    "course_filter": None,
    "pending_rating": None,   # {"question": ..., "answer": ..., "sources": ...}
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ── Step progress bar ──────────────────────────────────────────────────────────
STEPS = [("📥", "Data Sources"), ("🗃️", "Scrape & Preview"),
         ("🔑", "AI Setup"),     ("🧠", "Student Brain")]

def _render_steps():
    cols = st.columns(len(STEPS))
    for i, (icon, label) in enumerate(STEPS):
        with cols[i]:
            cur = st.session_state.step
            if i < cur:
                if st.button(f"✓ {icon} {label}", key=f"nav_{i}", use_container_width=True):
                    st.session_state.step = i
                    st.rerun()
            elif i == cur:
                st.markdown(
                    f'<div style="text-align:center;padding:9px 4px;border-radius:8px;'
                    f'background:#1f6feb;color:white;font-weight:bold;font-size:.9rem">'
                    f'{icon} {label}</div>', unsafe_allow_html=True)
            else:
                st.markdown(
                    f'<div style="text-align:center;padding:9px 4px;border-radius:8px;'
                    f'background:#21262d;color:#8b949e;font-size:.9rem">'
                    f'{icon} {label}</div>', unsafe_allow_html=True)

_render_steps()
st.write("")

def _nav(back=True, next_label="Next →", next_ok=True):
    b, _, n = st.columns([1, 4, 1])
    with b:
        if back and st.session_state.step > 0:
            if st.button("← Back", use_container_width=True):
                st.session_state.step -= 1; st.rerun()
    with n:
        if st.session_state.step < len(STEPS) - 1:
            if st.button(next_label, type="primary",
                         use_container_width=True, disabled=not next_ok):
                st.session_state.step += 1; st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# STEP 0 — DATA SOURCES
# ══════════════════════════════════════════════════════════════════════════════
def render_step0():
    st.header("📥 Step 1 of 4 — Data Sources")
    st.caption("Add the websites you want to scrape. Canvas is pre-loaded.")

    col_list, col_add = st.columns([3, 2], gap="large")
    ICONS = {"canvas": "🎓", "django": "🌐", "generic": "🤖"}

    with col_list:
        st.subheader("Configured Sites")
        for i, site in enumerate(st.session_state.sites):
            with st.container(border=True):
                r1, r2 = st.columns([6, 1])
                with r1:
                    checked = st.checkbox(
                        f"{ICONS.get(site['type'],'🌐')} **{site['name']}**  \n`{site['url']}`",
                        value=site["selected"], key=f"chk_{i}")
                    st.session_state.sites[i]["selected"] = checked
                    if site["type"] == "generic":
                        st.caption(f"Model: `{site.get('model','claude-sonnet-4-6')}`")
                    if site["type"] == "canvas":
                        with st.expander("🔑 Update access token"):
                            st.caption(
                                "**To generate a token:** go to "
                                "[Canvas → Profile Settings](https://rady.instructure.com/profile/settings) "
                                "→ scroll to **Approved Integrations** → click **+ New Access Token** "
                                "→ copy the token and paste it below."
                            )
                            new_token = st.text_input(
                                "New access token", type="password",
                                placeholder="Paste token here…", key=f"token_input_{i}")
                            if st.button("Save token", key=f"save_token_{i}") and new_token:
                                st.session_state.sites[i]["token"] = new_token
                                st.success("Token updated.")
                                st.rerun()
                with r2:
                    if site["id"] != "canvas":
                        if st.button("✕", key=f"del_{i}", help="Remove"):
                            st.session_state.sites.pop(i); st.rerun()

    with col_add:
        st.subheader("Add a Site")
        existing = {s["id"] for s in st.session_state.sites}
        rsm_e, rsm_p = os.getenv("RSM_EMAIL",""), os.getenv("RSM_PASSWORD","")

        qa1, qa2 = st.columns(2)
        with qa1:
            if st.button("+ MGTA 495", use_container_width=True,
                         disabled="django_mgta495" in existing):
                st.session_state.sites.append({
                    "id":"django_mgta495","name":"MGTA 495 — GenAI for Business",
                    "type":"django","url":"https://rsm-django-02.ucsd.edu/mgta495/",
                    "slug":"mgta495","base_url":"https://rsm-django-02.ucsd.edu",
                    "email":rsm_e,"password":rsm_p,"selected":True})
                st.rerun()
        with qa2:
            if st.button("+ MGTA 455", use_container_width=True,
                         disabled="django_mgta455" in existing):
                st.session_state.sites.append({
                    "id":"django_mgta455","name":"MGTA 455 — Customer Analytics",
                    "type":"django","url":"https://rsm-django-02.ucsd.edu/mgta455/",
                    "slug":"mgta455","base_url":"https://rsm-django-02.ucsd.edu",
                    "email":rsm_e,"password":rsm_p,"selected":True})
                st.rerun()

        st.divider()
        site_type = st.radio("Type", ["Django (RSM)", "Generic Website", "Canvas"],
                             horizontal=True)

        if site_type == "Django (RSM)":
            with st.form("add_django", clear_on_submit=True):
                name=st.text_input("Display name"); base_url=st.text_input("Base URL",value="https://rsm-django-02.ucsd.edu")
                slug=st.text_input("Course slug"); email=st.text_input("Email",value=rsm_e)
                pw=st.text_input("Password",type="password",value=rsm_p)
                if st.form_submit_button("Add",use_container_width=True) and name and slug:
                    st.session_state.sites.append({"id":f"django_{slug}","name":name,"type":"django",
                        "url":f"{base_url.rstrip('/')}/{slug}/","slug":slug,
                        "base_url":base_url.rstrip("/"),"email":email,"password":pw,"selected":True})
                    st.rerun()

        elif site_type == "Generic Website":
            with st.form("add_generic", clear_on_submit=True):
                name=st.text_input("Display name"); url=st.text_input("URL")
                kc,hc=st.columns([5,1])
                with kc: api_key=st.text_input("Anthropic API key",type="password",value=os.getenv("ANTHROPIC_API_KEY",""))
                with hc:
                    st.write("")
                    with st.popover("❓"):
                        st.markdown("1. [console.anthropic.com](https://console.anthropic.com)\n2. API Keys → Create Key")
                model=st.selectbox("Model",["claude-sonnet-4-6","claude-opus-4-8","claude-haiku-4-5-20251001"])
                if st.form_submit_button("Add",use_container_width=True) and name and url and api_key:
                    st.session_state.sites.append({"id":f"generic_{len(st.session_state.sites)}","name":name,
                        "type":"generic","url":url,"api_key":api_key,"model":model,"selected":True})
                    st.rerun()

        else:
            with st.form("add_canvas", clear_on_submit=True):
                name=st.text_input("Display name"); url=st.text_input("Canvas domain")
                tc, hc = st.columns([5, 1])
                with tc: token=st.text_input("Access token",type="password")
                with hc:
                    st.write("")
                    with st.popover("❓"):
                        st.markdown(
                            "1. Go to **Canvas → Profile Settings → Approved Integrations**\n"
                            "2. Click **+ New Access Token**\n"
                            "3. Set a name & expiry, then click **Generate Token**\n"
                            "4. Copy and paste the token here"
                        )
                if st.form_submit_button("Add",use_container_width=True) and name and url and token:
                    st.session_state.sites.append({"id":f"canvas_{len(st.session_state.sites)}",
                        "name":name,"type":"canvas","url":url,"token":token,"selected":True})
                    st.rerun()

    st.divider()
    sel = [s for s in st.session_state.sites if s["selected"]]
    _nav(back=False, next_label=f"Scrape {len(sel)} site(s) →", next_ok=len(sel)>0)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — SCRAPE & PREVIEW
# ══════════════════════════════════════════════════════════════════════════════
def render_step1():
    st.header("🗃️ Step 2 of 4 — Scrape & Preview")
    sel = [s for s in st.session_state.sites if s["selected"]]

    if not st.session_state.scrape_done:
        st.info(f"Ready to scrape **{len(sel)} site(s)**.")
        if st.button("▶ Start Scraping", type="primary"):
            all_ok = True
            with st.status("Scraping…", expanded=True) as status:
                for site in sel:
                    st.write(f"**{site['name']}**")
                    try:
                        if site["type"] == "canvas":    scrape_canvas(site, st.write)
                        elif site["type"] == "django":  scrape_django(site, st.write)
                        elif site["type"] == "generic":
                            scrape_generic(site, st.write,
                                show_code_fn=lambda c: st.code(c, language="python"))
                    except Exception as e:
                        st.error(f"Error: {e}"); all_ok = False
                status.update(label="Done ✓" if all_ok else "Errors", state="complete" if all_ok else "error")
            if all_ok:
                st.session_state.scrape_done = True; st.rerun()

    if st.session_state.scrape_done:
        _courses_dashboard()
        st.divider()
        _nav(next_label="Set up AI →")


def _courses_dashboard():
    st.success("✓ Course data ready")
    st.subheader("📊 What's in your knowledge base")
    rows = []
    for root, _, files in os.walk(COURSES_DIR):
        for fname in files:
            fpath = os.path.join(root, fname)
            rel   = os.path.relpath(fpath, COURSES_DIR)
            parts = rel.split(os.sep)
            course = parts[0][:45] if parts else "unknown"
            ext    = os.path.splitext(fname)[1].lower() or "other"
            size_kb = os.path.getsize(fpath) / 1024
            rows.append({"Course":course,"File":fname,"Type":ext,"Size (KB)":round(size_kb,1),"Path":rel})
    if not rows:
        st.warning("No files found."); return
    df = pd.DataFrame(rows)

    m1,m2,m3,m4 = st.columns(4)
    m1.metric("Total Files", f"{len(df):,}")
    m2.metric("Courses", df["Course"].nunique())
    m3.metric("File Types", df["Type"].nunique())
    m4.metric("Total Size", f"{df['Size (KB)'].sum()/1024:.1f} MB")
    st.write("")

    bar_col, pie_col = st.columns([3,2])
    with bar_col:
        st.markdown("**Files per Course**")
        st.bar_chart(df.groupby("Course").size().reset_index(name="Files").set_index("Course"), height=280)
    with pie_col:
        st.markdown("**By File Type**")
        try:
            import plotly.express as px
            tc = df.groupby("Type").size().reset_index(name="Count")
            fig = px.pie(tc, values="Count", names="Type", hole=0.4,
                         color_discrete_sequence=px.colors.qualitative.Set2)
            fig.update_layout(margin=dict(t=10,b=10,l=10,r=10), height=280)
            st.plotly_chart(fig, use_container_width=True)
        except Exception:
            st.dataframe(df.groupby("Type").size().reset_index(name="Count"), hide_index=True)

    with st.expander("📁 Browse all files"):
        st.dataframe(df[["Course","File","Type","Size (KB)"]].sort_values(["Course","File"]),
                     hide_index=True, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — AI SETUP
# ══════════════════════════════════════════════════════════════════════════════
def render_step2():
    st.header("🔑 Step 3 of 4 — AI Setup")
    st.caption("Enter your API keys and index your course materials.")

    key_col, idx_col = st.columns([1,1], gap="large")

    with key_col:
        st.subheader("API Keys")
        oc,oh = st.columns([5,1])
        with oc: openai_key = st.text_input("OpenAI API key", type="password", value=st.session_state.openai_key)
        with oh:
            st.write("")
            with st.popover("❓ How?"):
                st.markdown("""
**Get your OpenAI key**
1. [platform.openai.com](https://platform.openai.com) → sign in
2. **API Keys** → **+ Create new secret key**
3. Copy it (starts with `sk-...`)

Used for embeddings — very cheap (~$0.02/1M tokens).
                """)
        ac,ah = st.columns([5,1])
        with ac: anthropic_key = st.text_input("Anthropic API key", type="password", value=st.session_state.anthropic_key)
        with ah:
            st.write("")
            with st.popover("❓ How?"):
                st.markdown("""
**Get your Anthropic key**
1. [console.anthropic.com](https://console.anthropic.com) → sign in
2. **API Keys** → **+ Create Key**
3. Copy it (starts with `sk-ant-...`)
                """)

        model = st.selectbox("Claude model", ["claude-sonnet-4-6","claude-opus-4-8","claude-haiku-4-5-20251001"])
        top_k = st.slider("Chunks to retrieve", 3, 15, st.session_state.top_k)
        use_vision = st.checkbox("👁 Vision extraction for image-heavy PDFs",
                                 help="Uses Claude Haiku to extract text from slide images. "
                                      "Requires Anthropic API key. Slower but more complete.")
        save_env = st.checkbox("💾 Save keys to .env", value=True)

        if st.button("Save Settings", use_container_width=True):
            st.session_state.openai_key    = openai_key
            st.session_state.anthropic_key = anthropic_key
            st.session_state.model  = model
            st.session_state.top_k  = top_k
            if save_env and os.path.exists(ENV_FILE):
                set_key(ENV_FILE, "OPENAI_API_KEY",    openai_key)
                set_key(ENV_FILE, "ANTHROPIC_API_KEY", anthropic_key)
            st.success("Saved ✓")

    with idx_col:
        st.subheader("Index Course Files")
        st.caption("Parses PDFs, notebooks, text → embeds → ChromaDB + BM25")

        chunk_count = _chunk_count()
        if chunk_count > 0:
            st.success(f"✓ {chunk_count:,} chunks indexed")
            st.session_state.index_done = True

            new_cnt = _new_files_badge()
            if new_cnt:
                st.warning(f"⚠ {new_cnt} new file(s) detected since last index — re-index to include them.")
        else:
            st.info("Not indexed yet.")

        if st.button("🔄 Index / Re-index Courses", type="primary", use_container_width=True):
            key = openai_key or st.session_state.openai_key
            ant = (anthropic_key or st.session_state.anthropic_key) if use_vision else None
            if not key:
                st.error("OpenAI API key required.")
            else:
                with st.status("Indexing…", expanded=True) as status:
                    from brain.ingest import ingest_courses
                    try:
                        total = ingest_courses(COURSES_DIR, key, DB_PATH,
                                               log=st.write, anthropic_api_key=ant)
                        st.session_state.index_done = True
                        status.update(label=f"Done — {total:,} chunks ✓", state="complete")
                    except Exception as e:
                        status.update(label=f"Error: {e}", state="error")
                st.rerun()

        if _chunk_count() > 0:
            _index_dashboard()

    st.divider()
    _nav(next_label="Open Student Brain →", next_ok=st.session_state.index_done)


def _index_dashboard():
    try:
        import chromadb, plotly.express as px
        col  = chromadb.PersistentClient(path=DB_PATH).get_or_create_collection("student_brain")
        meta = col.get(include=["metadatas"])["metadatas"]
        if not meta: return
        df = pd.DataFrame(meta)

        c1,c2 = st.columns(2)
        c1.metric("Chunks", f"{len(df):,}")
        c2.metric("Courses", df["course"].nunique() if "course" in df.columns else "—")

        if "course" in df.columns:
            st.markdown("**Chunks per Course**")
            bc = df.groupby("course").size().reset_index(name="Chunks")
            bc["course"] = bc["course"].str[:35]
            st.bar_chart(bc.set_index("course"), height=200)
        if "file_type" in df.columns:
            ft = df.groupby("file_type").size().reset_index(name="Chunks")
            fig = px.pie(ft, values="Chunks", names="file_type", hole=0.4, height=180,
                         color_discrete_sequence=px.colors.qualitative.Pastel)
            fig.update_layout(margin=dict(t=20,b=0,l=0,r=0), showlegend=True)
            st.plotly_chart(fig, use_container_width=True)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — STUDENT BRAIN
# ══════════════════════════════════════════════════════════════════════════════
def render_step3():
    openai_key    = st.session_state.openai_key
    anthropic_key = st.session_state.anthropic_key
    chunks        = _chunk_count()

    if not openai_key or not anthropic_key:
        st.error("API keys missing — go back to Step 3."); _nav(next_ok=False); return

    # ── Course filter + tabs ──
    tab_chat, tab_study, tab_ratings = st.tabs(["💬 Chat", "📖 Study Tools", "📊 Ratings"])

    with tab_chat:
        _render_chat(openai_key, anthropic_key, chunks)

    with tab_study:
        _render_study(openai_key, anthropic_key, chunks)

    with tab_ratings:
        _render_ratings()


def _course_filter_widget(key_suffix=""):
    """Dropdown to scope retrieval to a single course."""
    courses = ["All courses"]
    try:
        import chromadb
        col  = chromadb.PersistentClient(path=DB_PATH).get_or_create_collection("student_brain")
        meta = col.get(include=["metadatas"])["metadatas"]
        courses += sorted({m.get("course","") for m in meta if m.get("course")})
    except Exception:
        pass
    choice = st.selectbox("🔍 Scope to course", courses, key=f"course_filter_{key_suffix}")
    return None if choice == "All courses" else choice


# ── Chat tab ──────────────────────────────────────────────────────────────────
def _render_chat(openai_key, anthropic_key, chunks):
    col_cfg, col_main = st.columns([1, 3], gap="large")

    with col_cfg:
        st.subheader("Settings")
        course_filter = _course_filter_widget("chat")
        model = st.selectbox("Model", ["claude-sonnet-4-6","claude-opus-4-8","claude-haiku-4-5-20251001"],
                             index=["claude-sonnet-4-6","claude-opus-4-8","claude-haiku-4-5-20251001"]
                             .index(st.session_state.model), key="chat_model")
        top_k = st.slider("Sources", 3, 15, st.session_state.top_k, key="chat_topk")
        st.caption(f"**{chunks:,}** chunks indexed")

        if st.button("🗑️ Clear chat", use_container_width=True):
            st.session_state.messages = []
            st.session_state.pending_rating = None
            st.rerun()

    with col_main:
        st.subheader(f"🧠 Student Brain {f'— {course_filter}' if course_filter else ''}")

        # Render history
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                if msg.get("sources"):
                    _sources_panel(msg["sources"], expanded=False)
                if msg.get("show_rating"):
                    _rating_buttons(msg["id"])

        # Handle new question
        if question := st.chat_input("Ask anything about your courses…"):
            if chunks == 0:
                st.error("No chunks indexed. Go back to Step 3."); return

            msg_id = len(st.session_state.messages)
            st.session_state.messages.append({"role":"user","content":question})

            with st.chat_message("user"):
                st.markdown(question)

            with st.chat_message("assistant"):
                from brain.query import query_brain_stream
                history = [{"role":m["role"],"content":m["content"]}
                           for m in st.session_state.messages[:-1]]
                try:
                    sources, stream = query_brain_stream(
                        question=question, openai_api_key=openai_key,
                        anthropic_api_key=anthropic_key, db_path=DB_PATH,
                        top_k=top_k, model=model,
                        history=history, course_filter=course_filter,
                    )
                except Exception as e:
                    st.error(f"Error: {e}"); return

                # Stream the answer token-by-token
                answer = st.write_stream(stream)
                _sources_panel(sources, expanded=True)
                _rating_buttons(msg_id + 1)

            st.session_state.messages.append({
                "id": msg_id + 1,
                "role": "assistant", "content": answer,
                "sources": sources, "question": question,
                "show_rating": True,
            })


def _sources_panel(sources: list[dict], expanded=False):
    if not sources:
        return
    with st.expander(f"📎 {len(sources)} source{'s' if len(sources)!=1 else ''}", expanded=expanded):
        for i, src in enumerate(sources, 1):
            lc, rc = st.columns([3, 1])
            with lc:
                label = f"**[{i}]** `{src['source']}`"
                if src.get("page"): label += f"  •  p.{src['page']}"
                st.markdown(label)
            with rc:
                score = src.get("score", 0)
                color = "#238636" if score > 0.7 else "#9e6a03" if score > 0.5 else "#8b949e"
                st.markdown(f'<div style="text-align:right;color:{color};font-weight:bold">'
                            f'{score:.0%}</div>', unsafe_allow_html=True)
            st.caption(src["text"][:350] + ("…" if len(src["text"]) > 350 else ""))
            if i < len(sources): st.divider()


def _rating_buttons(msg_id: int):
    from brain.ratings import log_rating
    rated_key = f"rated_{msg_id}"
    if st.session_state.get(rated_key):
        return  # already rated
    b1, b2, _ = st.columns([1, 1, 6])
    with b1:
        if st.button("👍", key=f"up_{msg_id}", help="Helpful"):
            _do_rate(msg_id, "up")
    with b2:
        if st.button("👎", key=f"dn_{msg_id}", help="Not helpful"):
            _do_rate(msg_id, "down")


def _do_rate(msg_id: int, rating: str):
    from brain.ratings import log_rating
    # Find the assistant message with this id
    for msg in reversed(st.session_state.messages):
        if msg.get("id") == msg_id and msg["role"] == "assistant":
            log_rating(msg.get("question",""), msg["content"], rating, msg.get("sources",[]))
            st.session_state[f"rated_{msg_id}"] = rating
            st.rerun()
            break


# ── Study Tools tab ───────────────────────────────────────────────────────────
def _render_study(openai_key, anthropic_key, chunks):
    if chunks == 0:
        st.info("Index your courses first (Step 3)."); return

    st.subheader("📖 Study Tools")
    col_cfg, col_out = st.columns([1, 2], gap="large")

    with col_cfg:
        tool = st.radio("Tool", ["🗂 Flashcards", "❓ Quiz", "📝 Summary"], label_visibility="collapsed")
        topic = st.text_input("Topic / Module", placeholder="e.g. RAG, uplift modeling, Module 05")
        course_filter = _course_filter_widget("study")
        n_items = st.slider("Number of items", 3, 15, 8)
        model = st.selectbox("Model", ["claude-sonnet-4-6","claude-haiku-4-5-20251001","claude-opus-4-8"],
                             key="study_model")
        generate = st.button("Generate", type="primary", use_container_width=True,
                             disabled=not topic.strip())

    with col_out:
        if not generate:
            st.caption("Configure a tool on the left and click **Generate**.")
            return

        if "Flashcards" in tool:
            with st.spinner("Generating flashcards…"):
                from brain.study import generate_flashcards
                cards, sources = generate_flashcards(topic, openai_key, anthropic_key,
                                                     DB_PATH, model=model, n=n_items,
                                                     course_filter=course_filter)
            st.success(f"{len(cards)} flashcards generated")
            for i, card in enumerate(cards, 1):
                with st.expander(f"**Card {i}:** {card.front}"):
                    st.markdown(f"**Answer:** {card.back}")
            _sources_panel(sources)

        elif "Quiz" in tool:
            with st.spinner("Generating quiz…"):
                from brain.study import generate_quiz
                questions, sources = generate_quiz(topic, openai_key, anthropic_key,
                                                   DB_PATH, model=model, n=n_items,
                                                   course_filter=course_filter)
            st.success(f"{len(questions)} questions generated")
            score_key = f"quiz_score_{topic}"
            if score_key not in st.session_state:
                st.session_state[score_key] = {}

            for i, q in enumerate(questions):
                st.markdown(f"**Q{i+1}.** {q.question}")
                ans_key = f"quiz_{topic}_{i}"
                choice  = st.radio("", q.options, key=ans_key, label_visibility="collapsed",
                                   index=None)
                if choice:
                    if choice == q.answer:
                        st.success(f"✓ Correct! {q.explanation}")
                    else:
                        st.error(f"✗ Correct answer: **{q.answer}**. {q.explanation}")
                st.write("")
            _sources_panel(sources)

        else:  # Summary
            with st.spinner("Summarizing…"):
                from brain.study import summarize_module
                summary, sources = summarize_module(topic, openai_key, anthropic_key,
                                                    DB_PATH, model=model,
                                                    course_filter=course_filter)
            st.markdown(summary)
            _sources_panel(sources)


# ── Ratings tab ───────────────────────────────────────────────────────────────
def _render_ratings():
    from brain.ratings import get_ratings, rating_summary
    st.subheader("📊 Answer Ratings")
    summary = rating_summary()
    if summary["total"] == 0:
        st.info("No ratings yet — use 👍/👎 in the Chat tab after answers."); return

    m1, m2, m3 = st.columns(3)
    m1.metric("Total rated", summary["total"])
    m2.metric("👍 Helpful", summary["up"])
    m3.metric("👎 Not helpful", summary["down"])

    pct = summary["up"] / summary["total"] * 100 if summary["total"] else 0
    st.progress(pct / 100, text=f"{pct:.0f}% helpful")
    st.write("")

    ratings = get_ratings()
    df = pd.DataFrame([{
        "Time":     r["timestamp"][:16].replace("T"," "),
        "Rating":   "👍" if r["rating"]=="up" else "👎",
        "Question": r["question"][:80],
        "Top Source": r["sources"][0] if r.get("sources") else "—",
    } for r in reversed(ratings)])
    st.dataframe(df, hide_index=True, use_container_width=True)

    # Show questions that got 👎 — these need improvement
    bad = [r for r in ratings if r["rating"] == "down"]
    if bad:
        with st.expander(f"⚠ {len(bad)} questions that need improvement"):
            for r in bad:
                st.markdown(f"- {r['question']}")


# ══════════════════════════════════════════════════════════════════════════════
# Router
# ══════════════════════════════════════════════════════════════════════════════
step = st.session_state.step
if   step == 0: render_step0()
elif step == 1: render_step1()
elif step == 2: render_step2()
elif step == 3: render_step3()
