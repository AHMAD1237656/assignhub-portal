
"use strict";

document.addEventListener("DOMContentLoaded", () => {
    const searchForms = document.querySelectorAll(
        "form[data-live-search]"
    );

    searchForms.forEach(initializeLiveSearch);
});


function initializeLiveSearch(form) {
    const resultsId = form.dataset.resultsTarget;
    const resultsBox = document.getElementById(resultsId);

    if (!resultsBox) {
        return;
    }

    const notice = form.parentElement.querySelector(
        "[data-search-notice]"
    );

    const debounceDelay = Math.max(
        0,
        Number(form.dataset.debounce) || 200
    );

    const programSelect = form.querySelector(
        'select[name="program"]'
    );

    const semesterSelect = form.querySelector(
        'select[name="semester"]'
    );

    const semestersApi = form.dataset.semestersApi;

    let debounceTimer = null;

    let searchController = null;
    let searchVersion = 0;

    let dropdownController = null;
    let dropdownVersion = 0;


    // -----------------------------------------------
    // HELPERS
    // -----------------------------------------------

    function setNotice(message) {
        if (notice) {
            notice.textContent = message;
        }
    }


    function cancelPendingSearch() {
        searchVersion += 1;

        if (debounceTimer !== null) {
            clearTimeout(debounceTimer);
            debounceTimer = null;
        }

        if (searchController) {
            searchController.abort();
            searchController = null;
        }
    }


    function buildSearchUrl(pageNumber = null) {
        const url = new URL(
            form.action,
            window.location.origin
        );

        const params = new URLSearchParams(
            new FormData(form)
        );

        params.delete("page");

        if (pageNumber !== null) {
            params.set(
                "page",
                String(pageNumber)
            );
        }

        url.search = params.toString();

        return url;
    }


    // -----------------------------------------------
    // AJAX RESULTS
    // -----------------------------------------------

    async function executeSearch(pageNumber = null) {
        const version = ++searchVersion;

        const controller = new AbortController();
        searchController = controller;

        const url = buildSearchUrl(pageNumber);

        setNotice("Searching...");

        try {
            const response = await fetch(
                url.toString(),
                {
                    method: "GET",
                    credentials: "same-origin",
                    headers: {
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    signal: controller.signal,
                }
            );

            if (!response.ok) {
                throw new Error(
                    `HTTP ${response.status}`
                );
            }

            const html = await response.text();

            if (version !== searchVersion) {
                return;
            }

            resultsBox.innerHTML = html;

            window.history.replaceState(
                window.history.state,
                "",
                url.pathname + url.search
            );

            setNotice("");

        } catch (error) {
            if (error.name === "AbortError") {
                return;
            }

            if (version === searchVersion) {
                setNotice(
                    "Search failed. Please retry."
                );
            }

        } finally {
            if (searchController === controller) {
                searchController = null;
            }
        }
    }


    // -----------------------------------------------
    // 200ms DEBOUNCE
    // -----------------------------------------------

    function scheduleSearch(
        pageNumber = null,
        immediate = false
    ) {
        cancelPendingSearch();

        const delay = immediate
            ? 0
            : debounceDelay;

        debounceTimer = window.setTimeout(
            () => {
                debounceTimer = null;
                executeSearch(pageNumber);
            },
            delay
        );
    }


    // -----------------------------------------------
    // TYPING AND DROPDOWN FILTERS
    // -----------------------------------------------

    form.addEventListener("input", (event) => {
        const target = event.target;

        if (
            target instanceof HTMLInputElement
            && ["q", "year"].includes(target.name)
        ) {
            scheduleSearch();
        }
    });


    form.addEventListener("change", (event) => {
        const target = event.target;

        if (!(target instanceof HTMLSelectElement)) {
            return;
        }

        if (
            target === programSelect
            && semesterSelect
            && semestersApi
        ) {
            updateSemesterOptions(
                target.value
            );
        }

        scheduleSearch();
    });


    // Fallback search button / Enter key.
    form.addEventListener("submit", (event) => {
        event.preventDefault();
        scheduleSearch(null, true);
    });


    // -----------------------------------------------
    // AJAX PAGINATION
    // -----------------------------------------------

    resultsBox.addEventListener("click", (event) => {
        if (!(event.target instanceof Element)) {
            return;
        }

        const link = event.target.closest(
            "a[data-ajax-page]"
        );

        if (!link) {
            return;
        }

        event.preventDefault();

        const url = new URL(
            link.href,
            window.location.origin
        );

        const pageNumber = url.searchParams.get(
            "page"
        );

        scheduleSearch(
            pageNumber,
            true
        );
    });


    // -----------------------------------------------
    // PROGRAM -> SEMESTER DEPENDENT DROPDOWN
    // -----------------------------------------------

    async function updateSemesterOptions(programId) {
        if (!semesterSelect || !semestersApi) {
            return;
        }

        dropdownVersion += 1;
        const version = dropdownVersion;

        if (dropdownController) {
            dropdownController.abort();
            dropdownController = null;
        }

        semesterSelect.replaceChildren(
            new Option(
                "All Semesters",
                ""
            )
        );

        semesterSelect.disabled = true;

        if (!programId) {
            return;
        }

        const controller = new AbortController();
        dropdownController = controller;

        const url = new URL(
            semestersApi,
            window.location.origin
        );

        url.searchParams.set(
            "program",
            programId
        );

        try {
            const response = await fetch(
                url.toString(),
                {
                    method: "GET",
                    credentials: "same-origin",
                    headers: {
                        "Accept": "application/json",
                    },
                    signal: controller.signal,
                }
            );

            if (!response.ok) {
                throw new Error(
                    `HTTP ${response.status}`
                );
            }

            const data = await response.json();

            if (version !== dropdownVersion) {
                return;
            }

            for (const item of data.results) {
                semesterSelect.add(
                    new Option(
                        item.label,
                        String(item.id)
                    )
                );
            }

            semesterSelect.disabled = false;

        } catch (error) {
            if (error.name === "AbortError") {
                return;
            }

            if (version === dropdownVersion) {
                setNotice(
                    "Unable to load semesters. " +
                    "Please select the program again."
                );
            }

        } finally {
            if (dropdownController === controller) {
                dropdownController = null;
            }
        }
    }
}
