let state = {
  data: null,
  reviews: {},
  selected: new Set(),
  hoverTimer: null,
  activePreview: null,
  previewCache: new Map()
};


// ------------------------------------------------------------
// Data loading
// ------------------------------------------------------------

async function getJson(path) {
  const response = await fetch(`${path}?t=${Date.now()}`, {
    cache: "no-store"
  });

  if (!response.ok) {
    throw new Error(`${path} returned HTTP ${response.status}`);
  }

  return response.json();
}


async function load() {
  try {
    const [data, reviews] = await Promise.all([
      getJson("data/results.json"),
      getJson("data/reviews.json")
    ]);

    state.data = data;
    state.reviews = reviews || {};

    updateStats();
    render();

  } catch (error) {
    console.error(error);

    const status = document.getElementById("status");

    if (status) {
      status.textContent = `Error loading scan data: ${error.message}`;
    }
  }
}


// ------------------------------------------------------------
// Review state
// ------------------------------------------------------------

function reviewed(id) {
  return !!state.reviews[String(id)];
}


// ------------------------------------------------------------
// Statistics
// ------------------------------------------------------------

function updateStats() {
  if (!state.data) return;

  const items = state.data.items || [];

  const reviewedCount = items.filter(
    item => reviewed(item.id)
  ).length;

  const newCount = items.filter(
    item => item.is_new
  ).length;

  const elements = {
    "last-scan": state.data.scan?.completed_at
      ? new Date(
          state.data.scan.completed_at
        ).toLocaleString()
      : "Unknown",

    "keyword-count":
      (state.data.keywords || []).length,

    "match-count":
      items.length,

    "new-count":
      newCount,

    "unreviewed-count":
      items.length - reviewedCount,

    "reviewed-count":
      reviewedCount
  };

  for (const [id, value] of Object.entries(elements)) {
    const element = document.getElementById(id);

    if (element) {
      element.textContent = value;
    }
  }
}


// ------------------------------------------------------------
// Filtering
// ------------------------------------------------------------

function visibleItems() {
  if (!state.data) return [];

  const query = (
    document.getElementById("q")?.value || ""
  ).trim().toLowerCase();

  const keyword = (
    document.getElementById("keyword")?.value || ""
  ).trim().toLowerCase();

  return (state.data.items || []).filter(item => {
    const haystack = [
      item.title || "",
      item.id || "",
      ...(item.keywords || [])
    ].join(" ").toLowerCase();

    const matchesQuery =
      !query || haystack.includes(query);

    const matchesKeyword =
      !keyword ||
      (item.keywords || [])
        .some(k => k.toLowerCase() === keyword);

    return matchesQuery && matchesKeyword;
  });
}


// ------------------------------------------------------------
// GitHub issue URLs
// ------------------------------------------------------------

function issueUrl(type, itemIds, note = "") {
  const repo = "Dranawor/SMSearcher";

  let body = "";

  if (type === "review") {
    body += "[REVIEW BULK]\n\n";
  } else {
    body += "[UNREVIEW BULK]\n\n";
  }

  body += "Workshop IDs:\n";

  for (const id of itemIds) {
    body += `- ${id}\n`;
  }

  body += "\nReview note:\n";
  body += note || "";

  body +=
    "\n\n---\n" +
    "This issue is used by SMSearcher to synchronize review status.";

  const title =
    type === "review"
      ? `Bulk review — ${itemIds.length} Workshop listings`
      : `Bulk unreview — ${itemIds.length} Workshop listings`;

  return (
    `https://github.com/${repo}/issues/new` +
    `?title=${encodeURIComponent(title)}` +
    `&body=${encodeURIComponent(body)}`
  );
}


// ------------------------------------------------------------
// Selection
// ------------------------------------------------------------

function selectVisible() {
  const items = visibleItems();

  const allSelected =
    items.length > 0 &&
    items.every(item =>
      state.selected.has(String(item.id))
    );

  if (allSelected) {
    for (const item of items) {
      state.selected.delete(String(item.id));
    }
  } else {
    for (const item of items) {
      state.selected.add(String(item.id));
    }
  }

  render();
}


function clearSelection() {
  state.selected.clear();
  render();
}


function bulkReview(type) {
  const ids = Array.from(state.selected);

  if (!ids.length) {
    alert("Select at least one Workshop listing first.");
    return;
  }

  // Keep batches small so the GitHub issue URL stays well
  // below browser/GitHub URL length limits.
  const batchSize = 20;

  const batches = [];

  for (let i = 0; i < ids.length; i += batchSize) {
    batches.push(ids.slice(i, i + batchSize));
  }

  for (let i = 0; i < batches.length; i++) {
    const url = issueUrl(type, batches[i]);

    // A slight delay reduces the likelihood of browsers
    // treating the additional tabs as unwanted popups.
    setTimeout(() => {
      window.open(url, "_blank");
    }, i * 300);
  }

  state.selected.clear();
  render();
}


// ------------------------------------------------------------
// Rendering
// ------------------------------------------------------------

function render() {
  if (!state.data) return;

  const container =
    document.getElementById("results");

  if (!container) return;

  const items = visibleItems();

  container.innerHTML = "";

  if (!items.length) {
    container.innerHTML = `
      <div class="empty">
        No listings match the current filters.
      </div>
    `;

    updateBulkBar();
    return;
  }

  for (const item of items) {
    const id = String(item.id);
    const isReviewed = reviewed(id);
    const isSelected = state.selected.has(id);

    const card = document.createElement("article");

    card.className =
      `result-card${isReviewed ? " reviewed" : ""}`;

    card.dataset.id = id;

    const keywords = (item.keywords || [])
      .map(keyword =>
        `<span class="tag">${esc(keyword)}</span>`
      )
      .join("");

    card.innerHTML = `
      <div class="result-select">
        <input
          type="checkbox"
          class="listing-checkbox"
          data-id="${esc(id)}"
          ${isSelected ? "checked" : ""}
          aria-label="Select ${esc(item.title || id)}"
        >
      </div>

      <div class="result-main">
        <div class="result-title-row">
          <a
            class="result-title"
            href="${esc(item.url)}"
            target="_blank"
            rel="noopener noreferrer"
          >
            ${esc(item.title || `Workshop item ${id}`)}
          </a>

          ${
            isReviewed
              ? `<span class="reviewed-badge">Reviewed</span>`
              : ""
          }

          ${
            item.is_new
              ? `<span class="new-badge">NEW</span>`
              : ""
          }
        </div>

        <div class="result-meta">
          Workshop ID: ${esc(id)}
        </div>

        <div class="result-keywords">
          ${keywords}
        </div>

        <div class="result-actions">
          <a
            class="button secondary dark"
            href="${esc(item.url)}"
            target="_blank"
            rel="noopener noreferrer"
          >
            Open Workshop
          </a>

          <button
            class="button review-button"
            type="button"
            data-review-id="${esc(id)}"
          >
            ${isReviewed ? "Mark Unreviewed" : "Mark Reviewed"}
          </button>
        </div>
      </div>
    `;

    // --------------------------------------------------------
    // Checkbox
    // --------------------------------------------------------

    const checkbox =
      card.querySelector(".listing-checkbox");

    checkbox.addEventListener("change", event => {
      const listingId = String(
        event.target.dataset.id
      );

      if (event.target.checked) {
        state.selected.add(listingId);
      } else {
        state.selected.delete(listingId);
      }

      updateBulkBar();
    });


    // --------------------------------------------------------
    // Review button
    // --------------------------------------------------------

    const reviewButton =
      card.querySelector(".review-button");

    reviewButton.addEventListener("click", event => {
      event.stopPropagation();

      const listingId =
        String(event.currentTarget.dataset.reviewId);

      const listing =
        (state.data.items || []).find(
          x => String(x.id) === listingId
        );

      if (!listing) return;

      const alreadyReviewed =
        reviewed(listingId);

      const repo =
        "Dranawor/SMSearcher";

      const prefix =
        alreadyReviewed
          ? "[UNREVIEW]"
          : "[REVIEW]";

      const title =
        `${prefix} ${listing.id} — ${listing.title || "Workshop item"}`;

      const body =
        `${prefix}\n\n` +
        `Workshop ID: ${listing.id}\n` +
        `Title: ${listing.title || "Workshop item"}\n` +
        `URL: ${listing.url}\n\n` +
        `Review note:\n`;

      const url =
        `https://github.com/${repo}/issues/new` +
        `?title=${encodeURIComponent(title)}` +
        `&body=${encodeURIComponent(body)}`;

      window.open(url, "_blank");
    });


    // --------------------------------------------------------
    // Hover preview
    // --------------------------------------------------------

    attachHoverPreview(card, item);

    container.appendChild(card);
  }

  updateBulkBar();
}


// ------------------------------------------------------------
// Hover preview
// ------------------------------------------------------------

function attachHoverPreview(card, item) {
  card.addEventListener("mouseenter", () => {
    clearTimeout(state.hoverTimer);

    state.hoverTimer = setTimeout(() => {
      showWorkshopPreview(card, item);
    }, 350);
  });

  card.addEventListener("mouseleave", () => {
    clearTimeout(state.hoverTimer);

    // Give the user a tiny amount of time to move from
    // the listing into the floating preview.
    setTimeout(() => {
      if (
        state.activePreview &&
        !state.activePreview.matches(":hover")
      ) {
        hideWorkshopPreview();
      }
    }, 100);
  });
}


function showWorkshopPreview(card, item) {
  hideWorkshopPreview();

  const id = String(item.id);

  // If we've already created the iframe for this item during
  // this browser session, reuse it.
  let preview = state.previewCache.get(id);

  if (!preview) {
    preview = createWorkshopPreview(item);
    state.previewCache.set(id, preview);
  }

  document.body.appendChild(preview);

  state.activePreview = preview;

  positionPreview(card, preview);

  preview.addEventListener("mouseleave", () => {
    hideWorkshopPreview();
  });
}


function hideWorkshopPreview() {
  if (state.activePreview) {
    state.activePreview.remove();
    state.activePreview = null;
  }
}


function createWorkshopPreview(item) {
  const wrapper = document.createElement("div");

  wrapper.className = "workshop-hover-preview";

  wrapper.innerHTML = `
    <div class="workshop-preview-header">
      <div class="workshop-preview-title">
        ${esc(item.title || `Workshop item ${item.id}`)}
      </div>

      <a
        href="${esc(item.url)}"
        target="_blank"
        rel="noopener noreferrer"
        class="workshop-preview-open"
      >
        Open ↗
      </a>
    </div>

    <div class="workshop-preview-frame">
      <iframe
        src="${esc(item.url)}"
        loading="lazy"
        title="${esc(item.title || "Steam Workshop preview")}"
        referrerpolicy="no-referrer"
      ></iframe>
    </div>

    <div class="workshop-preview-footer">
      <span>Workshop ID: ${esc(item.id)}</span>
      <span>Live Steam preview</span>
    </div>
  `;

  return wrapper;
}


function positionPreview(card, preview) {
  const rect = card.getBoundingClientRect();

  const width = 520;
  const height = 390;
  const margin = 12;

  let left = rect.right + margin;
  let top = rect.top;

  // If there isn't enough room on the right, put the
  // preview to the left of the listing.
  if (left + width > window.innerWidth - margin) {
    left = rect.left - width - margin;
  }

  // Keep the preview inside the viewport vertically.
  if (top + height > window.innerHeight - margin) {
    top = window.innerHeight - height - margin;
  }

  if (top < margin) {
    top = margin;
  }

  preview.style.left = `${Math.max(margin, left)}px`;
  preview.style.top = `${Math.max(margin, top)}px`;
}


// ------------------------------------------------------------
// Bulk bar
// ------------------------------------------------------------

function updateBulkBar() {
  const count =
    document.getElementById("selected-count");

  if (count) {
    count.textContent =
      state.selected.size;
  }

  const selectButton =
    document.getElementById("select-visible");

  const items = visibleItems();

  const allSelected =
    items.length > 0 &&
    items.every(item =>
      state.selected.has(String(item.id))
    );

  if (selectButton) {
    selectButton.textContent =
      allSelected
        ? "Deselect All"
        : "Select All";
  }
}


// ------------------------------------------------------------
// HTML helpers
// ------------------------------------------------------------

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}


// ------------------------------------------------------------
// Hover-preview CSS
//
// Injected here so you don't have to replace styles.css just
// to get the new feature working.
// ------------------------------------------------------------

const previewStyle =
  document.createElement("style");

previewStyle.textContent = `
  .workshop-hover-preview {
    position: fixed;
    z-index: 99999;
    width: 520px;
    height: 390px;
    background: #ffffff;
    border: 1px solid #cfcfcf;
    border-radius: 10px;
    box-shadow: 0 14px 40px rgba(0,0,0,.28);
    overflow: hidden;
    pointer-events: auto;
  }

  .workshop-preview-header {
    height: 48px;
    box-sizing: border-box;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 0 14px;
    border-bottom: 1px solid #dddddd;
    background: #f7f7f7;
  }

  .workshop-preview-title {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-weight: 700;
    font-size: 14px;
  }

  .workshop-preview-open {
    flex: 0 0 auto;
    text-decoration: none;
    font-size: 13px;
    font-weight: 600;
  }

  .workshop-preview-frame {
    width: 100%;
    height: 314px;
    background: #eeeeee;
    overflow: hidden;
  }

  .workshop-preview-frame iframe {
    display: block;
    width: 100%;
    height: 100%;
    border: 0;
  }

  .workshop-preview-footer {
    height: 28px;
    box-sizing: border-box;
    padding: 0 12px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 10px;
    font-size: 11px;
    color: #666666;
    background: #f7f7f7;
    border-top: 1px solid #dddddd;
  }

  @media (max-width: 900px) {
    .workshop-hover-preview {
      display: none;
    }
  }
`;

document.head.appendChild(previewStyle);


// ------------------------------------------------------------
// Event listeners
// ------------------------------------------------------------

document
  .getElementById("q")
  ?.addEventListener("input", render);

document
  .getElementById("keyword")
  ?.addEventListener("change", render);

document
  .getElementById("select-visible")
  ?.addEventListener("click", selectVisible);

document
  .getElementById("clear-selection")
  ?.addEventListener("click", clearSelection);

document
  .getElementById("bulk-review")
  ?.addEventListener(
    "click",
    () => bulkReview("review")
  );

document
  .getElementById("bulk-unreview")
  ?.addEventListener(
    "click",
    () => bulkReview("unreview")
  );


// ------------------------------------------------------------
// Start
// ------------------------------------------------------------

load();
