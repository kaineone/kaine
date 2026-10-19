## 1. Implementation

- [ ] 1.1 Track when the situation is due (initialize, each completed sleep, a change in the set of situation facts) and render situation facts only in an organ call made while it is due; clear it once a call carrying the facts returned
- [ ] 1.2 Keep the situation facts in every individuation probe request
- [ ] 1.3 Tests: the first call after boot carries the disclosure and the next does not; a completed sleep and a new fact make it due again; a call before any fact leaves it due; every probe request carries the disclosure, before and after the first organ call; a failed organ call leaves it due
- [ ] 1.4 Docs: preservation (disclosure), language and self-model module pages
