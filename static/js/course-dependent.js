
"use strict";

document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(
        "form[data-dependent-type]"
    ).forEach(initializeDependentForm);
});


function initializeDependentForm(form) {
    const type = form.dataset.dependentType;

    if (type === "course") {
        initializeCourseForm(form);
        return;
    }

    if (type === "offering") {
        initializeOfferingForm(form);
    }
}


function createDropdownLoader(parent, child, apiUrl, parameter) {
    if (!parent || !child || !apiUrl) {
        return null;
    }

    let controller = null;
    let version = 0;

    const initialPlaceholder = child.options.length
        ? child.options[0].textContent
        : "Select an option";

    async function loadOptions(parentValue, preserveValue = false) {
        version += 1;
        const requestVersion = version;

        if (controller) {
            controller.abort();
        }

        const previousValue = preserveValue
            ? child.value
            : "";

        child.replaceChildren(
            new Option(initialPlaceholder, "")
        );

        child.disabled = true;

        if (!parentValue) {
            return;
        }

        controller = new AbortController();

        const url = new URL(
            apiUrl,
            window.location.origin
        );

        url.searchParams.set(parameter, parentValue);

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
                throw new Error(`HTTP ${response.status}`);
            }

            const data = await response.json();

            if (requestVersion !== version) {
                return;
            }

            (data.results || []).forEach((item) => {
                child.add(
                    new Option(
                        item.label,
                        String(item.id)
                    )
                );
            });

            child.disabled = false;

            if (
                previousValue &&
                Array.from(child.options).some(
                    option => option.value === previousValue
                )
            ) {
                child.value = previousValue;
            }

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
    }

    parent.addEventListener("change", () => {
        loadOptions(parent.value);
    });

    return {
        loadOptions,
    };
}


function initializeCourseForm(form) {
    const department = form.querySelector("#id_department");
    const program = form.querySelector("#id_program");
    const semester = form.querySelector("#id_semester");

    const programsUrl = form.dataset.programsUrl;
    const semestersUrl = form.dataset.semestersUrl;

    if (
        !department ||
        !program ||
        !semester ||
        !programsUrl ||
        !semestersUrl
    ) {
        return;
    }

    const programLoader = createDropdownLoader(
        department,
        program,
        programsUrl,
        "department"
    );

    const semesterLoader = createDropdownLoader(
        program,
        semester,
        semestersUrl,
        "program"
    );

    if (!programLoader || !semesterLoader) {
        return;
    }

    department.addEventListener("change", () => {
        semester.replaceChildren(
            new Option("Select Semester", "")
        );

        semester.disabled = true;
    });

    program.addEventListener("change", () => {
        semester.replaceChildren(
            new Option("Select Semester", "")
        );

        semester.disabled = true;
    });

    // Preserve existing edit/create selections.
    program.disabled = false;
    semester.disabled = false;
}


function initializeOfferingForm(form) {
    const department = form.querySelector("#id_department");
    const program = form.querySelector("#id_program");
    const course = form.querySelector("#id_course");
    const section = form.querySelector("#id_section");

    const programsUrl = form.dataset.programsUrl;
    const coursesUrl = form.dataset.coursesUrl;
    const sectionsUrl = form.dataset.sectionsUrl;

    if (
        !department ||
        !program ||
        !course ||
        !section ||
        !programsUrl ||
        !coursesUrl ||
        !sectionsUrl
    ) {
        return;
    }

    // Department -> Program
    createDropdownLoader(
        department,
        program,
        programsUrl,
        "department"
    );

    // Program -> Course
    createDropdownLoader(
        program,
        course,
        coursesUrl,
        "program"
    );

    // Course -> Section
    createDropdownLoader(
        course,
        section,
        sectionsUrl,
        "course"
    );

    // Changing Department invalidates Course and Section.
    department.addEventListener("change", () => {
        course.replaceChildren(
            new Option("Select Course", "")
        );

        course.disabled = true;

        section.replaceChildren(
            new Option("Select Section", "")
        );

        section.disabled = true;
    });

    // Changing Program invalidates Section.
    program.addEventListener("change", () => {
        section.replaceChildren(
            new Option("Select Section", "")
        );

        section.disabled = true;
    });

    // Existing edit/create selections are already rendered.
    // Do not reload them on initial page load.
    program.disabled = false;
    course.disabled = false;
    section.disabled = false;
}
