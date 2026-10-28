
(() => {
    "use strict";

    const root = document.getElementById("timed-writing");

    if (!root) {
        return;
    }

    const clock = document.getElementById("writing-clock");
    const statusNode = document.getElementById("writing-state");
    const saveButton = document.getElementById("writing-save");
    const finishButton = document.getElementById("writing-finish");

    function show(message, type = "pending") {
        statusNode.textContent = message;
        statusNode.dataset.state = type;
    }

    if (!window.Quill || !window.katex) {
        show(
            "Editor libraries failed to load. Check your internet connection.",
            "error"
        );
        clock.textContent = "Unavailable";
        return;
    }

    const tokenNode = document.querySelector(
        '#writing-csrf input[name="csrfmiddlewaretoken"]'
    );

    if (!tokenNode) {
        show("CSRF token missing.", "error");
        return;
    }

    const csrf = tokenNode.value;

    let quill;

    try {
        quill = new window.Quill("#writing-editor", {
            theme: "snow",
            placeholder: "Write your assignment answer here...",
            modules: {
                toolbar: "#writing-toolbar"
            },
            formats: [
                "header",
                "bold",
                "italic",
                "underline",
                "strike",
                "color",
                "background",
                "script",
                "list",
                "blockquote",
                "align",
                "indent",
                "link",
                "formula",
                "shape"
            ]
        });

        const initialDelta = JSON.parse(
            document.getElementById(
                "initial-rich-delta"
            ).textContent
        );

        const initialText = JSON.parse(
            document.getElementById(
                "initial-plain-answer"
            ).textContent
        );

        if (
            initialDelta &&
            Array.isArray(initialDelta.ops) &&
            initialDelta.ops.length
        ) {
            quill.setContents(initialDelta, "silent");
        } else {
            quill.setText(initialText || "", "silent");
        }

    } catch (error) {
        show(
            "Editor initialization failed. Check browser console.",
            "error"
        );
        console.error(error);
        return;
    }

    let revision = Number(root.dataset.revision);

    let serverOffset = (
        Number(root.dataset.serverNow) * 1000
        - Date.now()
    );

    const expiry = Number(root.dataset.expiry) * 1000;

    let busy = false;
    let locked = false;
    let saveFailed = false;

    // -----------------------------------------
    // DOCUMENT STATE
    // -----------------------------------------

    function getDocument() {
        return quill.getContents();
    }

    function fingerprint(documentData) {
        return JSON.stringify(documentData.ops || []);
    }

    let lastSaved = fingerprint(getDocument());

    function isDirty() {
        return fingerprint(getDocument()) !== lastSaved;
    }

    // -----------------------------------------
    // SERVER TIMER
    // -----------------------------------------

    function serverNow() {
        return Date.now() + serverOffset;
    }

    function remainingSeconds() {
        return Math.max(
            0,
            Math.ceil(
                (expiry - serverNow()) / 1000
            )
        );
    }

    function lockEditor(message) {
        locked = true;

        quill.disable();
        saveButton.disabled = true;
        finishButton.disabled = true;

        show(message, "error");
    }

    function tick() {
        const seconds = remainingSeconds();

        const minutes = Math.floor(seconds / 60);
        const rest = seconds % 60;

        clock.textContent = (
            String(minutes).padStart(2, "0")
            + ":"
            + String(rest).padStart(2, "0")
        );

        clock.classList.toggle(
            "is-urgent",
            seconds <= 60
        );

        if (seconds === 0 && !locked) {
            lockEditor(
                "Time expired. Checking the last saved answer..."
            );

            checkServer();
        }
    }

    async function checkServer() {
        try {
            const response = await fetch(
                root.dataset.statusUrl,
                {
                    credentials: "same-origin",
                    cache: "no-store"
                }
            );

            if (!response.ok) {
                throw new Error("Status request failed");
            }

            const data = await response.json();

            serverOffset = (
                data.server_now * 1000
                - Date.now()
            );

            if (data.status !== "ACTIVE") {
                lockEditor(
                    data.status === "SUBMITTED"
                        ? "Answer finalized. Refresh to view the saved submission."
                        : "Time expired without a saved answer."
                );
                return;
            }

            if (
                data.revision !== revision &&
                !busy
            ) {
                lockEditor(
                    "This answer changed in another tab. Copy any unsaved text before refreshing."
                );
            }

        } catch (error) {
            if (!locked && !busy) {
                show(
                    "Unable to verify timer. Check connection.",
                    "error"
                );
            }
        }
    }

    // -----------------------------------------
    // ANSWER VALIDATION
    // -----------------------------------------

    function hasAnswer() {
        if (quill.getText().trim()) {
            return true;
        }

        return getDocument().ops.some(
            (op) => (
                op.insert &&
                typeof op.insert === "object" &&
                (
                    typeof op.insert.formula === "string" ||
                    typeof op.insert.shape === "object"
                )
            )
        );
    }

    // -----------------------------------------
    // PROFESSIONAL SUBMISSION MODAL
    // -----------------------------------------

    function confirmFinalSubmission() {
        return new Promise((resolve) => {
            const modalElement = document.getElementById(
                "finalSubmitModal"
            );

            const confirmBtn = document.getElementById(
                "finalSubmitConfirmBtn"
            );

            if (
                !modalElement ||
                !confirmBtn ||
                !window.bootstrap ||
                !window.bootstrap.Modal
            ) {
                show(
                    "Submission confirmation is unavailable. Please refresh the page.",
                    "error"
                );

                resolve(false);
                return;
            }

            const modal = window.bootstrap.Modal.getOrCreateInstance(
                modalElement,
                {
                    backdrop: "static",
                    keyboard: false
                }
            );

            let confirmed = false;
            let settled = false;

            function cleanup() {
                confirmBtn.removeEventListener(
                    "click",
                    onConfirm
                );

                modalElement.removeEventListener(
                    "hidden.bs.modal",
                    onHidden
                );
            }

            function finish(result) {
                if (settled) {
                    return;
                }

                settled = true;
                cleanup();
                resolve(result);
            }

            function onConfirm() {
                if (locked || busy || remainingSeconds() <= 0) {
                    modal.hide();

                    show(
                        "Submission is no longer available. Check the timer.",
                        "error"
                    );

                    return;
                }

                confirmed = true;
                modal.hide();
            }

            function onHidden() {
                finish(confirmed);
            }

            confirmBtn.addEventListener(
                "click",
                onConfirm
            );

            modalElement.addEventListener(
                "hidden.bs.modal",
                onHidden
            );

            try {
                modal.show();
            } catch (error) {
                console.error(
                    "Submission modal failed:",
                    error
                );

                finish(false);

                show(
                    "Unable to open confirmation dialog.",
                    "error"
                );
            }
        });
    }

    // -----------------------------------------
    // AUTOSAVE AND FINAL SUBMISSION
    // -----------------------------------------

    async function save(action = "save") {
        if (busy || locked) {
            return false;
        }

        if (
            action === "save" &&
            !isDirty()
        ) {
            show(
                "All changes already saved to server",
                "saved"
            );
            return true;
        }

        if (
            action === "finish" &&
            !hasAnswer()
        ) {
            show(
                "Write an answer before submitting.",
                "error"
            );
            return false;
        }

        busy = true;

        saveButton.disabled = true;
        finishButton.disabled = true;

        show(
            action === "finish"
                ? "Submitting final answer..."
                : "Saving answer...",
            "pending"
        );

        const snapshot = getDocument();

        try {
            const response = await fetch(
                root.dataset.saveUrl,
                {
                    method: "POST",
                    credentials: "same-origin",
                    cache: "no-store",

                    headers: {
                        "Content-Type": "application/json",
                        "X-CSRFToken": csrf
                    },

                    body: JSON.stringify({
                        answer: quill.getText(),
                        delta: snapshot,
                        revision: revision,
                        action: action
                    })
                }
            );

            const data = await response.json();

            if (!response.ok) {
                saveFailed = true;

                if (response.status === 409) {
                    lockEditor(
                        "Submission closed or revision conflict. Your unsaved text remains visible for copying."
                    );
                } else {
                    show(
                        data.error || "Save failed.",
                        "error"
                    );
                }

                return false;
            }

            revision = data.revision;
            lastSaved = fingerprint(snapshot);
            saveFailed = false;

            serverOffset = (
                data.server_now * 1000
                - Date.now()
            );

            if (data.status !== "ACTIVE") {
                locked = true;
                quill.disable();

                show(
                    "Final answer submitted successfully.",
                    "saved"
                );

                window.location.reload();
                return true;
            }

            show(
                isDirty()
                    ? "New changes pending..."
                    : "Saved to server",
                isDirty() ? "pending" : "saved"
            );

            return true;

        } catch (error) {
            saveFailed = true;

            show(
                "Connection error. Latest changes are NOT saved.",
                "error"
            );

            return false;

        } finally {
            busy = false;

            if (!locked) {
                saveButton.disabled = false;
                finishButton.disabled = false;
            }
        }
    }

    // -----------------------------------------
    // TEXT INSERTION
    // -----------------------------------------

    function insertText(value) {
        if (locked || !value) {
            return;
        }

        const range = quill.getSelection(true);

        quill.insertText(
            range
                ? range.index
                : quill.getLength() - 1,
            value,
            "user"
        );

        quill.focus();
    }

    // -----------------------------------------
    // MATHEMATICAL EQUATIONS
    // -----------------------------------------

    function insertEquation(latex) {
        if (locked || !latex) {
            return;
        }

        if (latex.length > 2000) {
            show(
                "Equation is too long.",
                "error"
            );
            return;
        }

        try {
            const range = quill.getSelection(true);

            const index = range
                ? range.index
                : quill.getLength() - 1;

            quill.insertEmbed(
                index,
                "formula",
                latex,
                "user"
            );

            quill.setSelection(
                index + 1,
                0,
                "silent"
            );

            quill.focus();

        } catch (error) {
            show(
                "Invalid equation. Check LaTeX syntax.",
                "error"
            );
        }
    }

    // -----------------------------------------
    // SYMBOL TOOL
    // -----------------------------------------

    document.getElementById(
        "insert-symbol"
    ).addEventListener(
        "click",
        () => {
            const select = document.getElementById(
                "math-symbol"
            );

            insertText(select.value);
            select.value = "";
        }
    );

    // -----------------------------------------
    // EQUATION PRESETS
    // -----------------------------------------

    document.getElementById(
        "insert-equation"
    ).addEventListener(
        "click",
        () => {
            const select = document.getElementById(
                "math-preset"
            );

            insertEquation(select.value);
            select.value = "";
        }
    );

    // -----------------------------------------
    // CUSTOM LATEX
    // -----------------------------------------

    document.getElementById(
        "custom-equation"
    ).addEventListener(
        "click",
        () => {
            if (locked) {
                return;
            }

            const latex = window.prompt(
                "Enter LaTeX equation:",
                "\\frac{a}{b}"
            );

            if (latex !== null) {
                insertEquation(latex.trim());
            }
        }
    );

    // -----------------------------------------
    // SHAPE INSERTION
    // -----------------------------------------

    document.getElementById(
        "insert-shape"
    ).addEventListener(
        "click",
        () => {
            if (locked) {
                return;
            }

            const kind = document.getElementById(
                "shape-kind"
            ).value;

            const entered = window.prompt(
                "Shape label (optional):",
                ""
            );

            if (entered === null) {
                return;
            }

            const label = entered.slice(0, 80);
            const range = quill.getSelection(true);

            const index = range
                ? range.index
                : quill.getLength() - 1;

            quill.insertEmbed(
                index,
                "shape",
                {
                    kind: kind,
                    label: label
                },
                "user"
            );

            quill.setSelection(
                index + 1,
                0,
                "silent"
            );

            quill.focus();
        }
    );

    // -----------------------------------------
    // DOCUMENT CHANGE HANDLING
    // -----------------------------------------

    quill.on(
        "text-change",
        (delta, oldDelta, source) => {
            if (
                source === "user" &&
                !locked
            ) {
                show(
                    "Unsaved changes",
                    "pending"
                );
            }
        }
    );

    // -----------------------------------------
    // MANUAL SAVE BUTTON
    // -----------------------------------------

    saveButton.addEventListener(
        "click",
        () => save("save")
    );

    // -----------------------------------------
    // FINAL SUBMISSION BUTTON
    // UPDATED: CUSTOM BOOTSTRAP MODAL
    // -----------------------------------------

    finishButton.addEventListener(
        "click",
        async () => {
            if (locked || busy) {
                return;
            }

            if (!hasAnswer()) {
                show(
                    "Write an answer first.",
                    "error"
                );
                return;
            }

            const confirmed = await confirmFinalSubmission();

            if (confirmed && !locked && !busy) {
                await save("finish");
            }
        }
    );

    // -----------------------------------------
    // UNSAVED CHANGES WARNING
    // -----------------------------------------

    window.addEventListener(
        "beforeunload",
        (event) => {
            if (
                !locked &&
                (
                    busy ||
                    isDirty() ||
                    saveFailed
                )
            ) {
                event.preventDefault();
                event.returnValue = "";
            }
        }
    );

    // -----------------------------------------
    // INITIALIZE EDITOR
    // -----------------------------------------

    saveButton.disabled = false;
    finishButton.disabled = false;

    show(
        "Editor ready — saved version loaded",
        "saved"
    );

    tick();

    // Countdown every second
    setInterval(tick, 1000);

    // Autosave every four seconds
    setInterval(
        () => {
            if (
                !locked &&
                !busy &&
                isDirty()
            ) {
                save("save");
            }
        },
        4000
    );

    // Check server state every ten seconds
    setInterval(
        checkServer,
        10000
    );
})();
