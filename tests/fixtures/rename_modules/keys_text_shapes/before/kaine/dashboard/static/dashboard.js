/* SPDX-License-Identifier: LicenseRef-CAL-0.4 */
if (msg.source === "thymos" && msg.type === "thymos.state") { render(); }
if (msg.type === "hypnos.sleep.started") { sleepStart(); }
var overlay = document.getElementById("nexus-logout");
