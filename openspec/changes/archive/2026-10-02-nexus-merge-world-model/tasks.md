## 1. Dashboard
- [x] 1.1 `kaine/nexus/templates/_diagnostics_sections.html`: a labelled select `#merge-world-model` (values "", "a", "b") in the merge form.
- [x] 1.2 `kaine/nexus/static/nexus.js`: the merge handler adds `world_model_from` only for "a"/"b", resets the select after success, and on failure shows the status and the server's detail (a string, or the messages of a validation-error list).

## 2. Tests
- [x] 2.1 A node harness loads `nexus.js`, attaches the controls to stub elements, submits the merge form, and checks the request body for B, for none, and the failure status text for a 409 with detail and a 422 validation list.
- [x] 2.2 The diagnostics page renders the select with a label.

## 3. Docs
- [x] 3.1 `docs/05-nexus.md` describes the form's world-model choice.
