
"use strict";

document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(
        "form[data-dependent-type]"
    ).forEach(initializeDependentForm);
});


function initializeDependentForm(form) {
    const type = form.dataset.dependentType;

    let parent;
    let child;
    let apiUrl;
    let parameter;

    if (type === "course") {
        parent = form.querySelector("#id_program");
        child = form.querySelector("#id_semester");
        apiUrl = form.dataset.semestersUrl;
        parameter = "program";

    } else if (type === "offering") {
        parent = form.querySelector("#id_course");
        child = form.querySelector("#id_section");
        apiUrl = form.dataset.sectionsUrl;
        parameter = "course";

    } else {
        return;
    }

    if (!parent || !child || !apiUrl) {
        return;
    }

    let controller = null;
    let version = 0;

    const initialPlaceholder = child.options.length
        ? child.options[0].textContent
        : "Select an option";


    parent.addEventListener("change", async () => {
        version += 1;
        const requestVersion = version;

        if (controller) {
            controller.abort();
        }

        child.replaceChildren(
            new Option(initialPlaceholder, "")
        );

        child.disabled = true;

        if (!parent.value) {
            return;
        }

        controller = new AbortController();

        const url = new URL(
            apiUrl,
            window.location.origin
        );

        url.searchParams.set(
            parameter,
            parent.value
        );

        try {
            const response = await fetch(
                url.toString(),
                {
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

            if (requestVersion !== version) {
                return;
            }

            data.results.forEach((item) => {
                child.add(
                    new Option(
                        item.label,
                        String(item.id)
                    )
                );
            });

            child.disabled = false;

        } catch (error) {
            if (error.name === "AbortError") {
                return;
            }

            if (requestVersion === version) {
                child.replaceChildren(
                    new Option(
                        "Unable to load options",
                        ""
                    )
                );
            }
        }
    });
}
