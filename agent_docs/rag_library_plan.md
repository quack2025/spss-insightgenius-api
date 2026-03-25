# RAG Library for SPSS Files — Implementation Plan

## Problem

Users upload .sav files, analyze them once, and the file disappears after 30 minutes (Redis session). There's no way to:
- Keep files across sessions
- Search across multiple studies ("which study measured NPS?")
- Compare results between files
- Build institutional memory of research data

## Solution: SPSS File Library with Semantic Search

A persistent library where files are stored in Supabase, metadata is indexed with embeddings, and Sonnet can search across the entire library to answer questions.

## Architecture

```
User uploads .sav
  → Supabase Storage (persistent, encrypted)
  → Metadata extracted → Supabase DB (files, variables, analyses)
  → Embeddings generated → pgvector (variable labels, file descriptions)
  → Available in chat: "Compare NPS across all my studies"
```

### Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| File storage | Supabase Storage (bucket: `spss-files`) | Persistent, cheap, encrypted |
| Metadata DB | Supabase PostgreSQL (`piclftokhzkdywupdyjo`) | Already provisioned, pgvector built-in |
| Embeddings | Voyage AI or OpenAI `text-embedding-3-small` | $0.00002/1K tokens, pgvector compatible |
| Search | pgvector `<=>` cosine similarity | SQL-native, no external service |
| Cache | Redis (existing) | Hot file cache for active analysis |
| AI | Sonnet (existing chat service) | Orchestrates search + analysis |

---

## Database Schema

### Tables

```sql
-- Persistent file library (replaces ephemeral Redis sessions)
create table library_files (
    id uuid default gen_random_uuid() primary key,
    user_id text not null references profiles(id) on delete cascade,
    filename text not null,
    original_name text not null,
    file_type text not null default 'sav',  -- sav, csv, xlsx
    storage_path text not null,  -- supabase storage path
    size_bytes bigint not null,
    n_cases int,
    n_variables int,
    file_label text,  -- SPSS file label
    description text,  -- user-provided description
    tags text[] default '{}',  -- user tags: ["haircare", "colombia", "2026"]
    study_context jsonb default '{}',  -- {objective, country, industry, methodology}
    created_at timestamptz default now(),
    last_accessed_at timestamptz default now()
);

-- Variable metadata per file (denormalized for search)
create table library_variables (
    id uuid default gen_random_uuid() primary key,
    file_id uuid not null references library_files(id) on delete cascade,
    name text not null,
    label text,
    var_type text,  -- numeric, string, date
    detected_type text,  -- likert_5, nps, binary, demographic, mrs, scale
    n_categories int default 0,
    value_labels jsonb,  -- {"1": "Male", "2": "Female"}
    n_valid int,
    n_missing int,
    -- Embedding for semantic search
    label_embedding vector(256),  -- pgvector
    unique(file_id, name)
);

-- Cached analysis results (avoid re-computing)
create table library_analyses (
    id uuid default gen_random_uuid() primary key,
    file_id uuid not null references library_files(id) on delete cascade,
    analysis_type text not null,  -- frequency, crosstab, correlation, tabulate
    spec_hash text not null,  -- SHA256 of the analysis spec (for cache lookup)
    spec jsonb not null,  -- the full analysis specification
    results_summary jsonb,  -- key findings (T2B, mean, sig differences)
    download_url text,  -- if Excel was generated
    created_at timestamptz default now(),
    unique(file_id, spec_hash)
);

-- File-level embedding for "find studies about X"
create table library_file_embeddings (
    id uuid default gen_random_uuid() primary key,
    file_id uuid not null references library_files(id) on delete cascade,
    content_type text not null,  -- 'file_summary', 'variable_list', 'study_context'
    content_text text not null,  -- the text that was embedded
    embedding vector(256),
    unique(file_id, content_type)
);

-- Indexes
create index idx_library_files_user on library_files(user_id);
create index idx_library_variables_file on library_variables(file_id);
create index idx_library_analyses_file on library_analyses(file_id);
create index idx_library_variables_embedding on library_variables using ivfflat (label_embedding vector_cosine_ops);
create index idx_library_file_embeddings on library_file_embeddings using ivfflat (embedding vector_cosine_ops);
```

### Supabase Storage

```
Bucket: spss-files
Path: {user_id}/{file_id}/{filename}
Policy: RLS — users can only access their own files
Max size: 200MB per file
```

---

## Implementation Sprints

### Sprint 1: File Persistence (replace Redis sessions)

**Goal**: Files survive beyond 30 minutes. Upload once, use forever.

**Changes:**

1. **New service**: `services/library_service.py`
   - `upload_file(user_id, file_bytes, filename)` → stores in Supabase Storage + creates library_files record + extracts metadata into library_variables
   - `get_file(file_id)` → downloads from Supabase Storage (with Redis cache for hot files)
   - `list_files(user_id)` → returns all files with metadata summary
   - `delete_file(file_id)` → removes from Storage + DB
   - `search_files(user_id, query)` → text search on filename, description, tags

2. **Update**: `routers/file_upload.py`
   - After Redis session creation, also persist to Supabase (async, non-blocking)
   - Return both `file_id` (Redis, fast) and `library_id` (Supabase, persistent)

3. **New page**: `/library` in frontend
   - Grid/list of uploaded files with name, date, n_cases, n_vars
   - Click to load into chat (copies to Redis session)
   - Delete button
   - Search bar (text search on filename + description)

4. **Supabase migration**: Create tables + storage bucket + RLS policies

**Effort**: ~1 day
**Files**: `services/library_service.py`, `routers/library.py`, `public/library.html`, migration SQL

---

### Sprint 2: Variable Metadata Indexing

**Goal**: Every uploaded file has its variables indexed for cross-file search.

**Changes:**

1. **On upload**: Extract all variable metadata using existing `extract_metadata()` and store in `library_variables`
   - Name, label, type, detected_type, value_labels, n_valid, n_missing
   - Detected groups (MRS, grids, demographics) stored as tags on the file

2. **New endpoint**: `GET /v1/library/{file_id}/variables`
   - Returns full variable list with labels and types
   - Supports filtering: `?type=likert_5&search=satisf`

3. **New endpoint**: `GET /v1/library/search/variables`
   - Search across ALL files: "find variables about satisfaction"
   - Text search on variable name + label across all library_variables

**Effort**: ~4 hours
**Files**: Update `services/library_service.py`, update `routers/library.py`

---

### Sprint 3: Semantic Search with Embeddings

**Goal**: "Which study measured brand awareness?" returns the right files.

**Changes:**

1. **Embedding generation** (on upload, async):
   - Embed variable labels: `"Q1: Overall Satisfaction with Service [likert_5, 5 cats]"` → vector
   - Embed file summary: `"Hair care study, Colombia, 493 cases, 291 variables. Key topics: satisfaction, brand awareness, purchase intent, demographics (age, city, gender)"` → vector
   - Use `text-embedding-3-small` (OpenAI) or Voyage AI — $0.00002/1K tokens ≈ $0.001/file

2. **New service**: `services/embedding_service.py`
   - `embed_text(text)` → vector[256]
   - `embed_file_metadata(file_id)` → generates + stores all embeddings for a file
   - `search_similar(query, user_id, top_k=5)` → pgvector cosine similarity search

3. **New endpoint**: `GET /v1/library/search?q=brand+awareness`
   - Semantic search: returns files ranked by relevance
   - Shows which variables matched and why

4. **Chat integration**: Sonnet gets a new tool:
   ```python
   {
       "name": "search_library",
       "description": "Search the user's file library for studies/variables matching a query",
       "input_schema": {
           "type": "object",
           "properties": {
               "query": {"type": "string", "description": "What to search for"},
               "file_type": {"type": "string", "enum": ["any", "sav", "csv", "xlsx"]},
           },
           "required": ["query"]
       }
   }
   ```

**Effort**: ~1 day
**Files**: `services/embedding_service.py`, update `services/library_service.py`, update `services/chat_service.py`
**Dependency**: OpenAI API key or Voyage AI key for embeddings

---

### Sprint 4: Cross-File Analysis

**Goal**: "Compare NPS between the Colombia and UK studies"

**Changes:**

1. **New Sonnet tool**: `compare_across_files`
   ```python
   {
       "name": "compare_files",
       "description": "Compare the same variable/metric across two files",
       "input_schema": {
           "properties": {
               "file_ids": {"type": "array", "items": {"type": "string"}, "minItems": 2},
               "variables": {"type": "array", "items": {"type": "string"}},
               "comparison_type": {"type": "string", "enum": ["frequency", "means", "crosstab"]},
           }
       }
   }
   ```

2. **Backend**: Load multiple files, run same analysis on each, return side-by-side comparison

3. **Frontend**: Comparison table/chart showing metrics from multiple files

**Effort**: ~1 day
**Files**: Update `services/chat_service.py`, new comparison logic in engine

---

### Sprint 5: Analysis Caching & History

**Goal**: Don't re-compute analyses. Show history of what was analyzed.

**Changes:**

1. **On every analysis**: Store spec + results summary in `library_analyses`
   - SHA256 hash of spec for cache lookup
   - Results summary (key numbers: T2B, mean, NPS, sig differences)
   - Download URL if Excel generated

2. **Cache check**: Before running analysis, check if same spec was already run
   - Same file + same spec hash → return cached result instantly

3. **History page**: `/library/{file_id}/history`
   - List of past analyses with timestamps
   - Re-download previous Excel exports
   - Re-run with different parameters

**Effort**: ~4 hours
**Files**: Update engine wrapper, update `services/library_service.py`

---

### Sprint 6: Smart Suggestions (RAG-powered)

**Goal**: System proactively suggests analyses based on what it knows about the data.

**Changes:**

1. **On file load**: Sonnet reads metadata + variable profiles → suggests:
   - "This file has 7 satisfaction scales — want a battery summary?"
   - "I detected 3 demographics (age, city, gender) — want crosstabs?"
   - "There's an NPS question (Q29_1) — want NPS by segment?"

2. **Cross-file suggestions**: When a new file is uploaded:
   - "This file has similar variables to 'UK NPS Study' — want to compare?"
   - "You analyzed satisfaction by region last time — want the same analysis here?"

3. **Implementation**: New `suggest_analyses(file_id, library_context)` in chat service

**Effort**: ~4 hours
**Files**: Update `services/chat_service.py`

---

## Frontend: Library UI

### `/library` page

```
┌──────────────────────────────────────────────────────────┐
│  My Library                                    [Upload]  │
│                                                          │
│  🔍 Search files and variables...                        │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │ 📊 spss.sav                            Mar 25, 2026│  │
│  │ Hair care study • Colombia • 493 cases × 291 vars  │  │
│  │ Tags: haircare, colombia, ego, satisfaction         │  │
│  │ Last analyzed: 2 hours ago                          │  │
│  │ [Open in Chat]  [Export]  [Delete]                  │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │ 📊 uber_nps_uk_demo_n1000.sav          Mar 19, 2026│  │
│  │ Uber NPS UK • 1000 cases × 19 vars                 │  │
│  │ Tags: nps, uber, uk, satisfaction, transport        │  │
│  │ Last analyzed: 5 days ago                           │  │
│  │ [Open in Chat]  [Export]  [Delete]                  │  │
│  └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

### Chat with library context

When user opens a file from library → loads into chat with full context:
- Previous analyses shown as history
- Sonnet knows what was analyzed before
- "Last time you ran crosstabs by region. Want to update with new data?"

---

## Cost Analysis

| Component | Cost per file upload | Cost per search | Monthly (100 files, 500 searches) |
|-----------|---------------------|-----------------|-----------------------------------|
| Supabase Storage | ~$0.02 (7MB avg) | — | $2 |
| Supabase DB | ~$0.001 | ~$0.0001 | $0.10 |
| Embeddings | ~$0.001 | ~$0.0001 | $0.15 |
| Sonnet (chat) | — | ~$0.02 | $10 |
| Redis (hot cache) | — | — | $5 (existing) |
| **Total** | | | **~$17/mo** |

---

## Priority Order

1. **Sprint 1** (File Persistence) — highest impact, unblocks everything
2. **Sprint 2** (Variable Indexing) — enables search
3. **Sprint 5** (Analysis Caching) — saves money + improves UX
4. **Sprint 3** (Semantic Search) — the "RAG" part
5. **Sprint 4** (Cross-File) — advanced use case
6. **Sprint 6** (Smart Suggestions) — polish

Sprint 1-2 can be done in 1-2 days. Sprint 3 adds ~1 day. Total for a functional library: **~3 days**.

---

## Key Decisions Needed

1. **Embedding provider**: OpenAI `text-embedding-3-small` ($0.02/1M tokens) vs Voyage AI vs local model
2. **Auth**: Currently demo mode (no auth). Library requires user identity. Use Clerk (already configured) or simple email-based?
3. **Storage limits**: How many files per user? How much storage per plan?
4. **Retention**: Auto-delete after 90 days of inactivity? Or keep forever?
