## 1. Fix

- [x] 1.1 Reproduce the failure under load and record the failing assertion
- [x] 1.2 Make both group-kill tests wait for the job's done event before reading its status, and assert the exact final status
- [x] 1.3 Run the cancel test 200 times under the same load with no failure
