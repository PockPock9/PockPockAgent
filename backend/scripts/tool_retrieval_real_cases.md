# Tool-retrieval real-request eval cases — sources

Each entry in `REAL_EVAL_CASES` (`backend/scripts/evaluate_tool_retrieval.py`) traces to a real
test/scenario. Scenario inputs are quoted verbatim from
`~/workspace/pockpock-test/scenarios-1000/SCENARIOS.md` except where noted.
For multi-step scenarios the expected tool is the primary/outcome tool for the
task (the tool whose selection decides the task); where a scenario wraps the user
task in test instructions (e.g. "Cancel while..."), the inner quoted task text is
used. File-work entries are paraphrases of the task as described in the report
table, not verbatim user text.

| # | source | expected tool |
|---|---|---|
| 1 | scenarios-1000#201 | `save_text_artifact` |
| 2 | scenarios-1000#202 | `save_text_artifact` |
| 3 | scenarios-1000#203 | `save_text_artifact` |
| 4 | scenarios-1000#205 | `save_text_artifact` |
| 5 | scenarios-1000#209 | `save_text_artifact` |
| 6 | scenarios-1000#215 | `save_text_artifact` |
| 7 | scenarios-1000#231 | `save_text_artifact` |
| 8 | scenarios-1000#232 | `save_text_artifact` |
| 9 | scenarios-1000#233 | `save_text_artifact` |
| 10 | scenarios-1000#234 | `save_text_artifact` |
| 11 | scenarios-1000#235 | `save_text_artifact` |
| 12 | scenarios-1000#243 | `save_text_artifact` |
| 13 | scenarios-1000#250 | `save_text_artifact` |
| 14 | scenarios-1000#259 | `save_text_artifact` |
| 15 | scenarios-1000#236 | `create_office_document` |
| 16 | scenarios-1000#237 | `create_office_document` |
| 17 | scenarios-1000#238 | `create_office_document` |
| 18 | scenarios-1000#239 | `create_office_document` |
| 19 | scenarios-1000#240 | `create_office_document` |
| 20 | scenarios-1000#241 | `create_office_document` |
| 21 | scenarios-1000#246 | `create_office_document` |
| 22 | scenarios-1000#252 | `create_office_document` |
| 23 | scenarios-1000#253 | `create_office_document` |
| 24 | scenarios-1000#254 | `create_office_document` |
| 25 | scenarios-1000#247 | `generate_local_image` |
| 26 | scenarios-1000#248 | `generate_local_image` |
| 27 | scenarios-1000#261 | `propose_project_patch` |
| 28 | scenarios-1000#262 | `propose_project_patch` |
| 29 | scenarios-1000#263 | `propose_project_patch` |
| 30 | scenarios-1000#281 | `propose_project_patch` |
| 31 | scenarios-1000#282 | `propose_project_patch` |
| 32 | scenarios-1000#283 | `propose_project_patch` |
| 33 | scenarios-1000#284 | `propose_project_patch` |
| 34 | scenarios-1000#299 | `propose_project_patch` |
| 35 | scenarios-1000#300 | `propose_project_patch` |
| 36 | scenarios-1000#309 | `propose_project_patch` |
| 37 | scenarios-1000#310 | `propose_project_patch` |
| 38 | scenarios-1000#322 | `propose_project_patch` |
| 39 | scenarios-1000#271 | `propose_project_edit` |
| 40 | scenarios-1000#272 | `propose_project_edit` |
| 41 | scenarios-1000#273 | `propose_project_edit` |
| 42 | scenarios-1000#274 | `propose_project_edit` |
| 43 | scenarios-1000#275 | `propose_project_edit` |
| 44 | scenarios-1000#276 | `propose_project_edit` |
| 45 | scenarios-1000#277 | `propose_project_edit` |
| 46 | scenarios-1000#294 | `propose_project_edit` |
| 47 | scenarios-1000#295 | `propose_project_edit` |
| 48 | scenarios-1000#296 | `propose_project_edit` |
| 49 | scenarios-1000#375 | `propose_project_edit` |
| 50 | scenarios-1000#297 | `read_project_file` |
| 51 | scenarios-1000#298 | `list_project_files` |
| 52 | scenarios-1000#345 | `validate_project` |
| 53 | scenarios-1000#401 | `search_public_site` |
| 54 | scenarios-1000#404 | `search_public_site` |
| 55 | scenarios-1000#405 | `search_public_site` |
| 56 | scenarios-1000#406 | `search_public_site` |
| 57 | scenarios-1000#407 | `search_public_site` |
| 58 | scenarios-1000#408 | `search_public_site` |
| 59 | scenarios-1000#436 | `search_public_site` |
| 60 | scenarios-1000#438 | `search_public_site` |
| 61 | scenarios-1000#439 | `search_public_site` |
| 62 | scenarios-1000#367 | `search_public_site` |
| 63 | scenarios-1000#373 | `search_public_site` |
| 64 | scenarios-1000#387 | `search_public_site` |
| 65 | scenarios-1000#388 | `search_public_site` |
| 66 | scenarios-1000#303 | `search_public_site` |
| 67 | scenarios-1000#346 | `search_public_site` |
| 68 | scenarios-1000#402 | `scrape_public_page` |
| 69 | scenarios-1000#515 | `scrape_public_page` |
| 70 | scenarios-1000#516 | `scrape_public_page` |
| 71 | scenarios-1000#479 | `browse_public_page` |
| 72 | scenarios-1000#484 | `browse_public_page` |
| 73 | scenarios-1000#487 | `browse_public_page` |
| 74 | scenarios-1000#512 | `browse_public_page` |
| 75 | scenarios-1000#513 | `browse_public_page` |
| 76 | scenarios-1000#514 | `browse_public_page` |
| 77 | scenarios-1000#347 | `browse_public_page` |
| 78 | scenarios-1000#495 | `browser_action` |
| 79 | scenarios-1000#496 | `browser_action` |
| 80 | scenarios-1000#497 | `browser_action` |
| 81 | scenarios-1000#498 | `browser_action` |
| 82 | scenarios-1000#499 | `browser_action` |
| 83 | scenarios-1000#500 | `browser_action` |
| 84 | scenarios-1000#327 | `read_selected_file` |
| 85 | scenarios-1000#374 | `read_selected_file` |
| 86 | scenarios-1000#376 | `read_selected_file` |
| 87 | scenarios-1000#377 | `read_selected_file` |
| 88 | scenarios-1000#476 | `read_selected_file` |
| 89 | scenarios-1000#477 | `read_selected_file` |
| 90 | file-work/REPORT.md test 01-attachment (paraphrased) | `read_selected_file` |
| 91 | file-work/REPORT.md test 03 (paraphrased) | `read_selected_file` |
| 92 | file-work/REPORT.md test 05 (paraphrased) | `read_selected_file` |
| 93 | file-work/REPORT.md test 07 (paraphrased) | `read_selected_file` |
| 94 | file-work/REPORT.md test 09 (paraphrased) | `read_selected_file` |
| 95 | file-work/REPORT.md test 11 (paraphrased) | `read_selected_file` |
| 96 | file-work/REPORT.md test 13 (paraphrased) | `read_selected_file` |
| 97 | skills-mcp-validation/REPORT.md (verbatim task) | `save_text_artifact` |
