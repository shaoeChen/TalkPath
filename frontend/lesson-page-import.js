(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.TalkPathPageImport = factory();
})(typeof window !== "undefined" ? window : globalThis, function () {
  "use strict";
  function retryAllowed(page) {
    return Boolean(page && (page.status === "failed" || page.status === "interrupted"));
  }

  function completionMessage(job) {
    const counts = job.counts || {};
    const added = counts.succeeded || 0;
    const retry = (counts.failed || 0) + (counts.interrupted || 0);
    return `Added ${added} ${added === 1 ? "page" : "pages"}. ${retry} ${retry === 1 ? "page needs" : "pages need"} retry.`;
  }

  function createPageImportController({ onUpdate, onComplete, seenStore } = {}) {
    const currentJobs = new Map();
    const seen = new Map();

    function jobs() {
      return Array.from(currentJobs.values());
    }

    function seenRevision(id) {
      let persisted = 0;
      try {
        if (seenStore) persisted = Number(seenStore.get(id)) || 0;
      } catch (_) {
        // Browsers may deny storage access; retain deduplication for this session.
      }
      return Math.max(seen.get(id) || 0, persisted);
    }

    function merge(job) {
      const previous = currentJobs.get(job.job_id);
      if (previous && job.revision <= previous.revision) return false;
      currentJobs.set(job.job_id, job);
      const announce = job.status === "completed" && job.completion_revision > 0
        && job.completion_revision > seenRevision(job.job_id);
      if (announce) {
        seen.set(job.job_id, job.completion_revision);
        try {
          if (seenStore) seenStore.set(job.job_id, job.completion_revision);
        } catch (_) {
          // The memory marker was already recorded before storage or callbacks.
        }
      }
      if (onUpdate) onUpdate(job, jobs());
      if (announce && onComplete) onComplete(job, completionMessage(job));
      return true;
    }

    function snapshot(values) {
      values.forEach(merge);
      return jobs();
    }

    return { merge, snapshot, jobs };
  }

  function buildSubmission({ entries, operationId, allowOverlap = false }) {
    if (!Array.isArray(entries) || entries.length === 0) {
      throw new Error("Choose at least one page image.");
    }
    const pages = entries.map((entry) => {
      if (!entry || !entry.file) throw new Error("Choose an image file for every page.");
      const page = String(entry.pageLabel || "").trim();
      if (!page) throw new Error("Enter a page label for every image.");
      return page;
    });
    const form = new FormData();
    form.append("operation_id", operationId);
    form.append("pages", JSON.stringify(pages));
    form.append("allow_overlap", String(Boolean(allowOverlap)));
    entries.forEach((entry, index) => {
      form.append("files", entry.file, entry.file.name || `page-${index + 1}`);
    });
    return form;
  }

  return { retryAllowed, completionMessage, createPageImportController, buildSubmission };
});
