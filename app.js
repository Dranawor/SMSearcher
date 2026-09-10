const $ = s => document.querySelector(s);
const state = {
  items: [],
  keywords: [],
  reviews: {},
  selected: new Set()
};

const REPO = "Dranawor/SMSearcher";

async function getJson(path, fallback) {
  try {
    const r = await fetch(`${path}?${Date.now()}`);
    return r.ok ? await r.json() : fallback;
  } catch {
    return fallback;
  }
}

async function load() {
  try {
    const d = await getJson("data/results.json", null);

    if (!d) {
      throw Error("No scan data is available yet.");
    }

    state.items = d.items || [];
    state.keywords = d.keywords || [];
    state.reviews = await getJson("data/reviews.json", {});

    $("#last-scan").textContent =
      d.scan?.completed_at
        ? new Date(d.scan.completed_at).toLocaleString()
        : "—";

    $("#keyword-count").textContent = state.keywords.length;
    $("#match-count").textContent = state.items.length;
    $("#new-count").textContent =
      state.items.filter(x => x.is_new).length;

    updateStats();

    for (const k of state.keywords) {
      const o = document.createElement("option");
      o.value = k;
      o.textContent = k;
      $("#keyword").append(o);
    }

    render();

  } catch (e) {
    $("#message").textContent = e.message;
  }
}

function reviewed(x) {
  return Boolean(
    state.reviews[String(x.id)]?.reviewed
  );
}

function updateStats() {
  const n = state.items.filter(x => !reviewed(x)).length;

  $("#unreviewed-count").textContent = n;
  $("#reviewed-count").textContent =
    state.items.length - n;
}

function visibleItems() {
  const q = $("#q").value.toLowerCase().trim();
  const k = $("#keyword").value;
  const s = $("#status").value;

  return state.items.filter(x => {
    const h = [
      x.title,
      x.creator,
      x.description,
      ...(x.keywords || [])
    ]
      .join(" ")
      .toLowerCase();

    const r = reviewed(x);

    return (
      (!q || h.includes(q)) &&
      (!k || (x.keywords || []).includes(k)) &&
      (
        s === "all" ||
        (s === "new" && x.is_new) ||
        (s === "unreviewed" && !r) ||
        (s === "reviewed" && r)
      )
    );
  });
}

function issueUrl(items, action = "REVIEW") {
  const bulk = items.length > 1;

  const title = bulk
    ? `[${action} BULK] ${items.length} Workshop listings`
    : `[${action}] ${items[0].id} — ${
        items[0].title || "Workshop listing"
      }`;

  const lines = [];

  if (bulk) {
    lines.push("Workshop IDs:");

    for (const x of items) {
      lines.push(`- ${x.id}`);
    }

  } else {
    lines.push(
      `Workshop listing: ${items[0].url}`,
      `Workshop ID: ${items[0].id}`,
      `Title: ${items[0].title || "Untitled"}`,
      `Keywords: ${(items[0].keywords || []).join(", ")}`
    );
  }

  lines.push(
    "",
    "Review note:",
    "",
    "---",
    "This issue is used by SMSearcher to maintain the shared review queue."
  );

  return (
    `https://github.com/${REPO}/issues/new?title=` +
    encodeURIComponent(title) +
    `&body=` +
    encodeURIComponent(lines.join("\n"))
  );
}

function selectVisible() {
  const vis = visibleItems();

  if (!vis.length) {
    return;
  }

  const allSelected = vis.every(
    x => state.selected.has(String(x.id))
  );

  for (const x of vis) {
    const id = String(x.id);

    if (allSelected) {
      state.selected.delete(id);
    } else {
      state.selected.add(id);
    }
  }

  render();
}

function bulkReview(action) {
  const items = state.items.filter(
    x => state.selected.has(String(x.id))
  );

  if (!items.length) {
    return;
  }

  /*
    GitHub has a maximum URL length.

    To avoid exceeding it, bulk selections are
    split into groups of 20 listings.
  */

  const batchSize = 20;
  const batches = [];

  for (let i = 0; i < items.length; i += batchSize) {
    batches.push(
      items.slice(i, i + batchSize)
    );
  }

  if (batches.length > 1) {
    const ok = confirm(
      `This selection contains ${items.length} listings. ` +
      `It will be split into ${batches.length} GitHub issues ` +
      `of up to ${batchSize} listings each. Continue?`
    );

    if (!ok) {
      return;
    }
  }

  batches.forEach((batch, i) => {
    const url = issueUrl(batch, action);

    setTimeout(() => {
      window.open(
        url,
        "_blank",
        "noopener"
      );
    }, i * 250);
  });
}

function render() {
  const a = visibleItems();

  $("#message").style.display =
    a.length ? "none" : "block";

  $("#results").innerHTML = a.map(x => {
    const r = state.reviews[String(x.id)];
    const img = safeImage(x.thumbnail);
    const checked =
      state.selected.has(String(x.id));

    return `
      <article class="card ${r ? "reviewed" : ""}">

        <div class="select-box">
          <input
            type="checkbox"
            class="item-check"
            data-id="${esc(x.id)}"
            ${checked ? "checked" : ""}
            aria-label="Select ${esc(
              x.title || "listing"
            )}"
          >
        </div>

        <div class="preview">

          ${
            img
              ? `
                <img
                  class="thumb"
                  src="${img}"
                  alt=""
                  loading="lazy"
                >
              `
              : `
                <div class="thumb placeholder">
                  No preview
                </div>
              `
          }

          <div class="card-main">

            <div class="card-head">

              <div>
                <div class="title">
                  ${esc(x.title || "Untitled")}
                </div>

                <div class="meta">
                  ${esc(
                    x.creator ||
                    "Unknown creator"
                  )}
                </div>
              </div>

              <div class="meta">

                ${
                  x.is_new
                    ? '<span class="tag new">NEW</span> '
                    : ""
                }

                ${
                  r
                    ? '<span class="tag reviewed-tag">REVIEWED</span>'
                    : ""
                }

              </div>

            </div>

            <div class="tags">
              ${(x.keywords || [])
                .map(
                  k =>
                    `<span class="tag">${esc(k)}</span>`
                )
                .join("")}
            </div>

            <div class="description">
              ${
                x.description
                  ? esc(
                      x.description.slice(0, 420)
                    ) +
                    (
                      x.description.length > 420
                        ? "…"
                        : ""
                    )
                  : "No description available."
              }
            </div>

            ${
              r
                ? `
                  <div class="review-info">

                    Reviewed by
                    <strong>
                      ${esc(
                        r.reviewer ||
                        "team member"
                      )}
                    </strong>

                    ${
                      r.reviewed_at
                        ? ` on ${esc(
                            new Date(
                              r.reviewed_at
                            ).toLocaleString()
                          )}`
                        : ""
                    }

                    ${
                      r.note
                        ? `<div>${esc(
                            r.note
                          )}</div>`
                        : ""
                    }

                  </div>
                `
                : ""
            }

            <div class="actions">

              <a
                class="button primary"
                href="${safe(x.url)}"
                target="_blank"
                rel="noopener"
              >
                Open Steam ↗
              </a>

              ${
                r
                  ? `
                    <a
                      class="button secondary dark"
                      href="${issueUrl(
                        [x],
                        "UNREVIEW"
                      )}"
                      target="_blank"
                      rel="noopener"
                    >
                      Undo Reviewed
                    </a>
                  `
                  : `
                    <a
                      class="button review"
                      href="${issueUrl([x])}"
                      target="_blank"
                      rel="noopener"
                    >
                      Mark Reviewed
                    </a>
                  `
              }

            </div>

          </div>

        </div>

      </article>
    `;
  }).join("");

  document
    .querySelectorAll(".item-check")
    .forEach(cb => {

      cb.addEventListener("change", () => {

        const id = String(
          cb.dataset.id
        );

        if (cb.checked) {
          state.selected.add(id);
        } else {
          state.selected.delete(id);
        }

        updateBulkBar();
      });

    });

  updateBulkBar();
}

function updateBulkBar() {
  const n = state.selected.size;

  $("#selected-count").textContent = n;

  const vis = visibleItems();

  const selectedVisible = vis.filter(
    x => state.selected.has(String(x.id))
  ).length;

  $("#select-visible").textContent =
    vis.length &&
    selectedVisible === vis.length
      ? "Deselect All"
      : "Select All";
}

function esc(s) {
  return String(s).replace(
    /[&<>"']/g,
    c => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;"
    }[c])
  );
}

function safe(u) {
  try {
    const x = new URL(u);

    return (
      x.protocol === "https:" &&
      x.hostname === "steamcommunity.com"
    )
      ? x.href
      : "#";

  } catch {
    return "#";
  }
}

function safeImage(u) {
  try {
    const x = new URL(u);

    return (
      x.protocol === "https:" &&
      (
        x.hostname ===
          "steamuserimages-a.akamaihd.net" ||
        x.hostname.endsWith(
          ".steamusercontent.com"
        ) ||
        x.hostname ===
          "steamcommunity.com"
      )
    )
      ? x.href
      : "";

  } catch {
    return "";
  }
}

["q", "keyword", "status"].forEach(id => {
  $("#" + id).addEventListener(
    "input",
    () => {
      state.selected.clear();
      render();
    }
  );
});

$("#select-visible").addEventListener(
  "click",
  selectVisible
);

$("#clear-selection").addEventListener(
  "click",
  () => {
    state.selected.clear();
    render();
  }
);

$("#bulk-review").addEventListener(
  "click",
  () => bulkReview("REVIEW")
);

$("#bulk-unreview").addEventListener(
  "click",
  () => bulkReview("UNREVIEW")
);

load();
