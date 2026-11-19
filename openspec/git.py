+# SPDX-License-Identifier: MIT
@@ -X,Y +X,Y @@
-    run(['git', 'merge', '--ff-only', branch], check=True)
+    try:
+        run(['git', 'merge', '--ff-only', branch], check=True)
+    except subprocess.CalledProcessError as e:
+        if b'Not possible to fast-forward' in e.stderr:
+            run(['git', 'merge', '--no-ff', branch], check=True)
+        else:
+            raise