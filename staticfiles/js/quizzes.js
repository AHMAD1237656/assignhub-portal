/* AssignHub quiz submit + autosave: server remains authoritative. */
(function () {
  'use strict';
  const root = document.getElementById('ahq-attempt');
  if (!root) return;
  const status = document.getElementById('ahq-status');
  const nearSubmit = document.getElementById('ahq-submit-status');
  const timer = document.getElementById('ahq-clock');
  const submitForm = document.getElementById('ahq-submit-form');
  const submitButton = document.getElementById('ahq-submit');
  const token = document.querySelector('#ahq-csrf-form input[name="csrfmiddlewaretoken"]');
  if (!submitForm || !submitButton || !token) return; // Native POST still works without JS.
  const csrf = token.value;
  const expiry = Number(root.dataset.expiry);
  const serverOffset = Number(root.dataset.serverNow) * 1000 - Date.now();
  const radios = Array.from(document.querySelectorAll('#ahq-attempt input[data-question]'));
  const queues = new Map();
  let expired = false;
  let submitting = false;

  function tell(message, isError) {
    status.textContent = message;
    if (nearSubmit) {
      nearSubmit.textContent = message;
      nearSubmit.classList.toggle('text-danger', !!isError);
      nearSubmit.classList.toggle('text-success', !isError);
    }
  }

  function postForm() {
    // Bypass the async submit listener. Native browser POST includes Django CSRF.
    HTMLFormElement.prototype.submit.call(submitForm);
  }

  function secondsLeft() {
    return Math.max(0, Math.ceil((expiry * 1000 - (Date.now() + serverOffset)) / 1000));
  }

  function clock() {
    const remaining = secondsLeft();
    timer.textContent = `${String(Math.floor(remaining / 60)).padStart(2, '0')}:${String(remaining % 60).padStart(2, '0')}`;
    timer.classList.toggle('urgent', remaining <= 60);
    if (remaining === 0 && !expired) {
      expired = true;
      submitting = true;
      submitButton.disabled = true;
      radios.forEach(input => { input.disabled = true; });
      tell('Time has ended. The server is finalizing saved answers.', false);
      // An expired attempt must always be settled, even if a late autosave fails.
      postForm();
    }
  }

  async function save(question, choice) {
    if (expired) return; // Only the server can accept answers until expiry.
    const response = await fetch(root.dataset.answerUrl, {
      method: 'POST',
      credentials: 'same-origin',
      cache: 'no-store',
      headers: {
        'X-CSRFToken': csrf,
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json'
      },
      body: new URLSearchParams({question_id: String(question), choice: String(choice)})
    });
    if (response.status === 409) {
      window.location.assign(root.dataset.resultUrl);
      throw new Error('Attempt already finished');
    }
    if (!response.ok) throw new Error('Autosave HTTP ' + response.status);
    const body = await response.json();
    if (!body.saved) throw new Error('Answer not confirmed saved');
  }

  radios.forEach(input => {
    input.addEventListener('change', () => {
      if (expired || submitting) return;
      const question = input.dataset.question;
      const choice = input.value;
      const preceding = queues.get(question) || Promise.resolve();
      tell('Saving your answer...', false);
      // Serialize writes for a single question; a late response cannot overwrite a newer choice.
      const task = preceding.catch(() => {}).then(() => save(question, choice));
      queues.set(question, task);
      task.then(() => {
        if (queues.get(question) === task && !submitting) tell('Answer saved.', false);
      }).catch(() => {
        if (queues.get(question) === task && !submitting) {
          tell('Answer could not be saved. Retry by selecting the answer again, or press Submit to retry.', true);
        }
      });
    });
  });

  submitForm.addEventListener('submit', async event => {
    event.preventDefault();
    if (submitting || expired) return;
    submitting = true;
    submitButton.disabled = true;
    radios.forEach(input => { input.disabled = true; });
    tell('Checking and saving your final answers...', false);
    try {
      const outstanding = [...queues.entries()];
      const settled = await Promise.allSettled(outstanding.map(([, promise]) => promise));
      const retry = outstanding.filter(([, p], i) => settled[i].status === 'rejected');
      if (retry.length) {
        // Explicitly retry ONLY previously failed questions with the most recent choice.
        for (const [qid] of retry) {
          const current = radios.find(input => input.dataset.question === qid && input.checked);
          if (!current) throw new Error('Missing answer after autosave error');
          const response = await fetch(root.dataset.answerUrl, {
            method: 'POST', credentials: 'same-origin', cache: 'no-store',
            headers: {'X-CSRFToken': csrf, 'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'},
            body: new URLSearchParams({question_id: String(qid), choice: current.value})
          });
          if (response.status === 409) { window.location.assign(root.dataset.resultUrl); return; }
          if (!response.ok || !(await response.json()).saved) throw new Error('Failed to save answer ' + qid);
        }
      }
      tell('Answers saved. Submitting quiz...', false);
      postForm();
    } catch (_error) {
      if (secondsLeft() === 0) {
        tell('Time finished. Submitting already saved answers...', false);
        postForm();
        return;
      }
      submitting = false;
      submitButton.disabled = false;
      radios.forEach(input => { input.disabled = false; });
      tell('Could not confirm all answers were saved. Check your internet and press Submit again.', true);
    }
  });
  clock();
  window.setInterval(clock, 1000);
})();
