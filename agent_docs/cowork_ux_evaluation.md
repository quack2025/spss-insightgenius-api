# Claude Co-Work: UX Evaluation of Talk2Data InsightGenius Chat

## Instructions

You are evaluating the web app at **https://spss.insightgenius.io/export-mcp**. This is a conversational analysis tool where market researchers upload SPSS files and ask questions in natural language. The AI (Claude Sonnet) calls a deterministic statistical engine to produce professional results.

## Test file

Use this SPSS file for testing: upload it via drag & drop on the page.
- File: `uber_nps_uk_demo_n1000.sav` (1000 cases, 19 variables, Uber NPS study in the UK)
- If you don't have this file, use any .sav file available, or ask Jorge for one.

## What to evaluate

### Phase 1: Upload & Data Prep

1. **Drag & drop the .sav file** onto the upload zone
   - Does the upload start immediately? Is there a progress indicator?
   - How long does it take? Is the user informed of what's happening?

2. **Data Preparation panel** — after upload, a panel should appear with:
   - MRS Groups (auto-detected awareness/multi-response questions)
   - Grid Batteries (auto-detected scale questions)
   - Demographics (suggested banner variables like age, gender, region)
   - Weight detection
   - Auto-detected Nets (T2B/B2B for Likert scales)
   - **Study Brief / Objectives** (optional text field)
   - Check: Are the toggles clear? Can you enable/disable groups?
   - Check: Does "Skip" go straight to chat? Does "Confirm" preserve selections?

3. **Reporting Ticket section** — after uploading a .sav, a .docx upload zone should appear
   - Is it visible? Is it clear it's optional?
   - If you have a .docx reporting ticket, try uploading it

### Phase 2: Chat Experience

4. **Welcome message** — after confirming prep:
   - Does it show file info (cases x variables)?
   - Does it list the detected data structure (MRS, grids, demographics)?
   - Are there **clickable suggestion buttons**? (Demographics, Full Excel, Key findings, Drivers, Suggest analyses)

5. **Test each suggestion button** (click them one by one):
   - **"Demographics overview"** — should show frequency tables of demographics with charts
   - **"Full Excel tabulation"** — should generate an Excel file with a download link
   - **"Key findings"** — should run multiple analyses and highlight significant patterns
   - **"Satisfaction drivers"** — should run correlations and identify what drives satisfaction
   - **"Suggest analyses"** — should recommend 5 specific analyses based on the data

6. **Streaming** — when you send a message:
   - Do you see text appearing progressively (word by word)?
   - Do you see "Running frequency..." or similar status during tool execution?
   - Or does it show nothing for 10-20 seconds then dump everything at once?

7. **Natural language queries** — try these specific prompts:
   - `"What is the NPS score by region?"` — should run frequency + crosstab
   - `"Cross all satisfaction questions by gender and age"` — should generate Excel with download
   - `"Is there a significant difference in satisfaction by income level?"` — should run ANOVA
   - `"What is the correlation between all satisfaction variables?"` — should show correlation matrix
   - `"Analyze satisfaction only for London residents"` — should apply filter (region=London)
   - `"Generate a gap analysis: importance vs performance for satisfaction metrics"` — should run gap analysis

8. **Charts** — when charts appear:
   - Do they render correctly? (bar charts, heatmaps, etc.)
   - Are they readable? Labels visible?
   - Do they match the data discussed?

9. **Downloads** — when an Excel is generated:
   - Is there a clear download link?
   - Does the download work? (click it)
   - Does the Excel have proper formatting, sig letters, nets?

10. **Copy button** — hover over any assistant response:
    - Does a "Copy" button appear?
    - Does it copy the text to clipboard?
    - Is the copied text clean markdown (usable in Gamma, Word, Slides)?

### Phase 3: Library

11. **My Files section** — on the upload page, below the drop zone:
    - Does it show previously uploaded files?
    - Can you click a file to load it into a new chat session?
    - Does the search input work? Try searching "satisfaction" or "nps"

### Phase 4: Error Handling

12. Try these edge cases:
    - Send an empty message (just press Enter)
    - Ask about a variable that doesn't exist: `"Analyze variable XYZ123"`
    - Ask for something impossible: `"Cross nps_score by itself"`
    - Refresh the page mid-chat — can you recover?

## What to report

For each item above, report:
- **Works** / **Partially works** / **Broken**
- **Screenshot** if something looks wrong
- **UX feedback**: Is it clear? Confusing? Missing context?
- **Performance**: How long did each operation take?

### Summary format

```
| # | Feature | Status | Notes |
|---|---------|--------|-------|
| 1 | Upload drag & drop | Works/Broken | ... |
| 2 | Data prep panel | Works/Broken | ... |
...
```

### Top 3 issues (ranked by impact on user experience)

1. ...
2. ...
3. ...

### Top 3 things that work well

1. ...
2. ...
3. ...
