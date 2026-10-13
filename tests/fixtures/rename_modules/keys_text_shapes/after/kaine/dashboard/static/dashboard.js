/* SPDX-License-Identifier: LicenseRef-CAL-0.4 */
if (msg.source === "affect" && msg.type === "affect.state") { render(); }
if (msg.type === "sleep.sleep.started") { sleepStart(); }
var overlay = document.getElementById("nexus-logout");
