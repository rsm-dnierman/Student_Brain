import streamlit as st
import os
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="Student Brain", page_icon="🧠", layout="wide")
st.title("🧠 Student Brain")
st.caption("Ask anything about your course materials — answers are cited back to the source.")

DB_PATH = "./chroma_db"

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.subheader("⚙️ Configuration")

    anthropic_key = st.text_input(
        "Anthropic API key",
        type="password",
        value=os.getenv("ANTHROPIC_API_KEY", ""),
        help="Used to generate answers via Claude.",
    )
    model = st.selectbox("Claude model", [
        "claude-sonnet-4-6",
        "claude-opus-4-8",
        "claude-haiku-4-5-20251001",
    ])
    top_k = st.slider("Chunks to retrieve", min_value=3, max_value=15, value=8,
                      help="How many passages from your course materials are sent to Claude as context. Higher = more coverage for broad questions but slower and more expensive. 8 is a good default.")

    st.divider()
    st.subheader("📚 Knowledge Base")

    # Index stats
    try:
        import chromadb
        _client = chromadb.PersistentClient(path=DB_PATH)
        _col = _client.get_or_create_collection("student_brain")
        chunk_count = _col.count()
    except Exception:
        chunk_count = 0

    st.metric("Indexed chunks", chunk_count)
    if chunk_count > 0:
        st.success("Brain is ready")
    else:
        st.warning("Not indexed yet")

    if st.button("🔄 Index / Re-index Courses", use_container_width=True):
        with st.status("Indexing course files...", expanded=True) as status:
            from brain.ingest import ingest_courses
            try:
                total = ingest_courses("./Courses", DB_PATH, log=st.write)
                status.update(label=f"Done! {total} chunks indexed ✓", state="complete")
            except Exception as e:
                status.update(label=f"Error: {e}", state="error")
        st.rerun()

    if chunk_count > 0 and st.button("🗑️ Clear Index", use_container_width=True):
        import chromadb, shutil
        shutil.rmtree(DB_PATH, ignore_errors=True)
        st.rerun()

# ── Chat ──────────────────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []

# Render history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if sources := msg.get("sources"):
            with st.expander(f"📎 {len(sources)} sources used"):
                for i, src in enumerate(sources, 1):
                    label = f"**[{i}]** `{src['source']}`"
                    if src.get("page"):
                        label += f"  •  page {src['page']}"
                    label += f"  •  relevance {src['score']:.0%}"
                    st.markdown(label)
                    st.caption(src["text"][:300] + ("…" if len(src["text"]) > 300 else ""))
                    st.divider()

# Input
if question := st.chat_input("Ask anything about your courses…"):
    if not anthropic_key:
        st.error("Set your Anthropic API key in the sidebar before asking questions.")
        st.stop()
    if chunk_count == 0:
        st.error("The knowledge base is empty. Click **Index / Re-index Courses** in the sidebar first.")
        st.stop()

    # Show user message
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    # Generate answer
    with st.chat_message("assistant"):
        with st.spinner("Searching course materials…"):
            from brain.query import query_brain
            try:
                result = query_brain(
                    question=question,
                    anthropic_api_key=anthropic_key,
                    db_path=DB_PATH,
                    top_k=top_k,
                    model=model,
                )
            except Exception as e:
                st.error(f"Error: {e}")
                st.stop()

        st.markdown(result["answer"])

        sources = result["sources"]
        with st.expander(f"📎 {len(sources)} sources used"):
            for i, src in enumerate(sources, 1):
                label = f"**[{i}]** `{src['source']}`"
                if src.get("page"):
                    label += f"  •  page {src['page']}"
                label += f"  •  relevance {src['score']:.0%}"
                st.markdown(label)
                st.caption(src["text"][:300] + ("…" if len(src["text"]) > 300 else ""))
                st.divider()

    st.session_state.messages.append({
        "role": "assistant",
        "content": result["answer"],
        "sources": result["sources"],
    })
