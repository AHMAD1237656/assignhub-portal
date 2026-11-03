/* AssignHub Smart Proctor AI — browser-only inference, no image/audio upload.
 * Detection flags are advisory and never automatically affect grading.
 * Third-party packages: Google MediaPipe Tasks Vision, TensorFlow.js, COCO-SSD.
 */
(() => {
  'use strict';
  const root = document.getElementById('ahp-monitor-root');
  if (!root || root.dataset.aiEnabled !== 'yes') return;
  const video = document.getElementById('ahp-live-video');
  const output = document.getElementById('ahp-ai-status');
  const faceOutput = document.getElementById('ahp-ai-face');
  const phoneOutput = document.getElementById('ahp-ai-phone');
  const token = document.querySelector('#ahq-csrf-form input[name="csrfmiddlewaretoken"]')?.value;
  if (!video || !token) { if (output) output.textContent = 'AI unavailable: webcam or security token missing.'; return; }

  const faceEnabled = root.dataset.detectMultiple === 'yes' || root.dataset.detectAbsence === 'yes' || root.dataset.detectHead === 'yes';
  const phoneEnabled = root.dataset.detectPhone === 'yes';
  const modelOrigin = 'https://cdn.jsdelivr.net/npm/';
  const MP_VERSION = '@mediapipe/tasks-vision@0.10.32';
  const TF_VERSION = '@tensorflow/tfjs@4.22.0';
  const COCO_VERSION = '@tensorflow-models/coco-ssd@2.2.3';
  const FACE_ASSET = 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task';
  // ASSIGNHUB-FACE-FALLBACK-V1: dedicated BlazeFace counting + landmark tracking.
  const FACE_COUNT_ASSET = 'https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite';
  // ASSIGNHUB-PHONE-DUAL-DETECTOR-V1
  // An independent EfficientDet-Lite0 model complements COCO-SSD.
  // Neither model is a verified phone-use/cheating detector.
  const OBJECT_MODEL_ASSET = 'https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite0/float16/1/efficientdet_lite0.tflite';
  let objectPhoneModel = null, objectPhoneReady = false, objectPhoneError = false;
  let objectPhoneVersion = 'EfficientDet-Lite0';
  const phoneCropCanvas = document.createElement('canvas');
  const phoneCropContext = phoneCropCanvas.getContext('2d');
  let phoneCropIndex = 0, phoneObjectDebugAt = 0;
  let faceModel = null, phoneModel = null, faceCountModel = null;
  let faceCountReady = false, faceCountError = false;
  let lastFocusTry = 0, lastDiagnostic = 0;
  const focusCanvas = document.createElement('canvas');
  const focusContext = focusCanvas.getContext('2d');
  // ASSIGNHUB-FACE-TEMPORAL-SMOOTHING-V1
  // A single missed video frame must not immediately imply a missing student.
  // These times are conservative starting points; validate on student hardware.
  let firstFaceFrameAt = 0;
  let lastPositiveFaceAt = 0;
  let lastConfirmedSingleAt = 0;
  const multipleFaceSamples = [];
  const FACE_VISIBLE_HOLD_MS = 3200;
  const FACE_ABSENCE_PRECONFIRM_MS = 1800;
  const FACE_FIRST_SAMPLE_GRACE_MS = 3500;
  const FACE_MULTIPLE_CONFIRM_WINDOW_MS = 3200;
  // ASSIGNHUB-PHONE-RECALL-V1: lower-confidence diagnostics with multi-sample confirmation.
  // Scores are model object confidence, NOT a probability of cheating.
  const PHONE_CANDIDATE_SCORE = 0.22;
  const PHONE_CONFIRM_SCORE = 0.32;
  const PHONE_STRONG_SCORE = 0.65;
  const PHONE_CONFIRM_WINDOW_MS = 10500;
  const phonePositiveSamples = [];
  let lastPhoneDebugAt = 0;
  let phoneModelVariant = 'mobilenet_v2';
  let active = true, faceLast = 0, phoneLast = 0, currentPhone = false;
  let faceError = false, phoneError = false, lastPhonePresent = 0;
  let neutral = null, neutralSamples = 0;
  const incidentStates = new Map();
  let faceReady = false, phoneReady = false;
  const initializedAt = Date.now();
  let missingCameraReported = false;
  let processing = false;
  const info = (text, problem = false) => {
    if (output) { output.textContent = text; output.classList.toggle('text-danger', problem); }
  };

  // Thresholds are provisional; pilot validation is required before operational use.
  const RULES = Object.freeze({
    NO_FACE: 5500,
    MULTIPLE_FACES: 1800,
    HEAD_TURNED: 5000,
    PHONE_VISIBLE: 2500,
  });
  // Emit at most once per uninterrupted episode and rate-limit across episodes.
  const sentAt = new Map();
  async function send(kind, durationMs, confidence, faces) {
    if (!active) return;
    const now = Date.now();
    if (now - (sentAt.get(kind) || 0) < 15000) return;
    sentAt.set(kind, now);
    const data = new URLSearchParams({kind, duration_s:String(Math.min(600, Math.max(0, Math.floor(durationMs / 1000))))});
    if (Number.isFinite(confidence)) data.set('confidence', String(Math.max(0, Math.min(1, confidence))));
    if (Number.isInteger(faces)) data.set('face_count', String(Math.min(5, Math.max(0, faces))));
    try {
      const response = await fetch(root.dataset.eventUrl, {
        method:'POST', credentials:'same-origin', cache:'no-store', keepalive:true,
        headers:{'X-CSRFToken':token, 'Content-Type':'application/x-www-form-urlencoded', 'Accept':'application/json'},
        body:data,
      });
      if (response.status === 403 || response.status === 404) active = false;
      if (!response.ok && active) {
        // Log the HTTP status and kind only. Never output webcam/video content.
        console.warn('AssignHub monitoring event failed', {
          kind, status: response.status, endpoint: root.dataset.eventUrl,
        });
        info(`AI incident logging failed (HTTP ${response.status}). Quiz answers still work.`, true);
      }
    } catch (_) { info('AI monitoring connection unavailable; quiz answers are independent.', true); }
  }

  function observe(kind, condition, at, confidence, count) {
    const state = incidentStates.get(kind) || {since:0, reported:false};
    if (!condition) { incidentStates.set(kind, {since:0, reported:false}); return; }
    if (!state.since) state.since = at;
    if (!state.reported && (at - state.since) >= RULES[kind]) {
      state.reported = true;
      send(kind, at - state.since, confidence, count);
    }
    incidentStates.set(kind, state);
  }

  function loadScript(url) {
    return new Promise((resolve, reject) => {
      const el = document.createElement('script');
      el.src = url; el.async = true; el.crossOrigin = 'anonymous';
      el.onload = resolve; el.onerror = () => reject(new Error('Could not load ' + url));
      document.head.appendChild(el);
    });
  }

  async function initFace() {
    let vision, fileset;
    try {
      vision = await import(modelOrigin + MP_VERSION + '/vision_bundle.mjs');
      if (!active) return;
      fileset = await vision.FilesetResolver.forVisionTasks(modelOrigin + MP_VERSION + '/wasm');
    } catch (err) {
      faceError = true;
      if (faceOutput) faceOutput.textContent = 'Face detection unavailable (model loading failed)';
      console.warn('AssignHub Face MediaPipe runtime load error', err);
      send('MONITOR_ERROR', 0);
      return;
    }
    // Run two independent tasks: BlazeFace counts visible faces; landmarks
    // are used only for the optional, coarse head-direction heuristic.
    // One model failing does NOT mean a face is absent.
    const [countTask, landmarkTask] = await Promise.allSettled([
      vision.FaceDetector.createFromOptions(fileset, {
        baseOptions:{modelAssetPath:FACE_COUNT_ASSET, delegate:'CPU'},
        runningMode:'VIDEO', minDetectionConfidence:0.35, minSuppressionThreshold:0.30,
      }),
      vision.FaceLandmarker.createFromOptions(fileset, {
        baseOptions:{modelAssetPath:FACE_ASSET, delegate:'CPU'},
        runningMode:'VIDEO', numFaces:4, minFaceDetectionConfidence:0.35,
        minFacePresenceConfidence:0.35, minTrackingConfidence:0.40,
      }),
    ]);
    if (!active) {
      if (countTask.status === 'fulfilled') countTask.value.close();
      if (landmarkTask.status === 'fulfilled') landmarkTask.value.close();
      return;
    }
    if (countTask.status === 'fulfilled') {
      faceCountModel = countTask.value;
      faceCountReady = true;
    } else {
      faceCountError = true;
      console.warn('AssignHub Face count detector load error', countTask.reason);
    }
    if (landmarkTask.status === 'fulfilled') {
      faceModel = landmarkTask.value;
      faceReady = true;
    } else {
      faceError = true;
      console.warn('AssignHub Face landmark model load error', landmarkTask.reason);
    }
    if (faceOutput) faceOutput.textContent = (faceCountReady || faceReady)
      ? 'Face detection ready — checking video frames'
      : 'Face detection unavailable (technical issue)';
    if (!faceCountReady && !faceReady) send('MONITOR_ERROR', 0);
    else if (!faceReady && root.dataset.detectHead === 'yes') {
      info('Face counting active; head-direction model unavailable. The exam continues.', true);
      send('MONITOR_ERROR', 0);
    }
    console.info('AssignHub face pipeline ready', {
      counting:faceCountReady, landmarks:faceReady,
      videoWidth:video.videoWidth, videoHeight:video.videoHeight,
    });
  }

  async function initPhone() {
    try {
      await loadScript(modelOrigin + TF_VERSION + '/dist/tf.min.js');
      await loadScript(modelOrigin + COCO_VERSION + '/dist/coco-ssd.min.js');
      if (!active || !window.cocoSsd) throw new Error('COCO-SSD not initialized');
      // COCO-SSD documents mobilenet_v2 as its highest-classification-accuracy base.
      // Fall back to original lite model if the larger model cannot be downloaded.
      try {
        phoneModel = await window.cocoSsd.load({base:'mobilenet_v2'});
      } catch (highAccuracyError) {
        console.warn('AssignHub high-accuracy phone model unavailable; using lite fallback',
                     String(highAccuracyError));
        phoneModelVariant = 'lite_mobilenet_v2';
        phoneModel = await window.cocoSsd.load({base:'lite_mobilenet_v2'});
      }
      phoneReady = true;
      if (phoneOutput) phoneOutput.textContent = 'Phone detector ready — scanning';
      console.info('AssignHub phone model ready', {model:phoneModelVariant});
    } catch (err) {
      phoneError = true;
      if (phoneOutput) phoneOutput.textContent = 'Phone detector unavailable';
      console.warn('AssignHub Phone model load error', err);
      send('MONITOR_ERROR', 0);
    }
  }

  async function initObjectPhone() {
    try {
      // Reuses the SAME MediaPipe version/wasm already used for face models;
      // the phone detector uses an independent, COCO-trained EfficientDet model.
      const vision = await import(modelOrigin + MP_VERSION + '/vision_bundle.mjs');
      if (!active) return;
      const fileset = await vision.FilesetResolver.forVisionTasks(modelOrigin + MP_VERSION + '/wasm');
      objectPhoneModel = await vision.ObjectDetector.createFromOptions(fileset, {
        baseOptions: {modelAssetPath: OBJECT_MODEL_ASSET, delegate: 'CPU'},
        runningMode: 'VIDEO', scoreThreshold: 0.17, maxResults: 20,
      });
      if (!active) { objectPhoneModel.close(); objectPhoneModel = null; return; }
      objectPhoneReady = true;
      console.info('AssignHub secondary phone detector ready', {model:objectPhoneVersion});
    } catch (error) {
      objectPhoneError = true;
      console.warn('AssignHub secondary phone model unavailable', error);
      // Failure does not prevent use of COCO-SSD or exam answers.
      if (!phoneReady && phoneOutput) phoneOutput.textContent = 'Phone models unavailable (technical issue)';
    }
  }

  // Category names differ by model; normalize only actual phone classes.
  function isPhoneLabel(label) {
    const value = String(label || '').toLowerCase().replace(/[^a-z0-9]/g, '');
    return value === 'cellphone' || value === 'mobilephone' || value === 'smartphone';
  }

  function parseObjectPhone(result) {
    const objects = (result?.detections || []).flatMap(d => (d.categories || []).map(c => ({
      label: String(c.categoryName || c.displayName || ''), score: Number(c.score || 0),
    })));
    const phones = objects.filter(o => isPhoneLabel(o.label)).sort((a,b) => b.score - a.score);
    return {objects, phones};
  }

  function headOffset(landmarks) {
    // Landmark displacement is a coarse head-direction proxy, NOT eye/gaze tracking.
    const nose = landmarks[1], left = landmarks[234], right = landmarks[454];
    const eyeLeft = landmarks[33], eyeRight = landmarks[263];
    if (!nose || !left || !right || !eyeLeft || !eyeRight) return null;
    const width = Math.abs(right.x - left.x);
    const eyeWidth = Math.abs(eyeRight.x - eyeLeft.x);
    if (width < 0.05 || eyeWidth < 0.04) return null;
    return {
      yaw: (nose.x - (left.x + right.x)/2) / width,
      pitch: (nose.y - (eyeLeft.y + eyeRight.y)/2) / eyeWidth,
    };
  }

  function assessFace(now) {
    if (!faceReady && !faceCountReady) return;
    const timestamp = performance.now();
    let landmarks = [], detectionCount = 0;
    let inferenceOk = false;
    if (faceCountReady && faceCountModel) {
      try {
        const result = faceCountModel.detectForVideo(video, timestamp);
        detectionCount = result?.detections?.length || 0;
        inferenceOk = true;
      } catch (err) {
        console.warn('Face-count inference error', err);
        faceCountReady = false;
        if (!faceCountError) { faceCountError = true; send('MONITOR_ERROR', 0); }
      }
    }
    if (faceReady && faceModel) {
      try {
        const result = faceModel.detectForVideo(video, timestamp);
        landmarks = result?.faceLandmarks || [];
        inferenceOk = true;
      } catch (err) {
        console.warn('Face landmark inference error', err);
        faceReady = false;
        if (!faceError) { faceError = true; send('MONITOR_ERROR', 0); }
      }
    }
    if (!inferenceOk) {
      if (faceOutput) faceOutput.textContent = 'Face detector interrupted (technical issue)';
      return;
    }
    let count = Math.max(landmarks.length, detectionCount);
    // Try a focused image when the full frame produces a false negative.
    // Some portrait webcams show broad letterboxing or leave the face small.
    // Retry never overrides an already positive full-frame face count.
    if (count === 0 && faceCountReady && focusContext && now - lastFocusTry > 2400 &&
        video.videoWidth >= 120 && video.videoHeight >= 120) {
      lastFocusTry = now;
      try {
        const w = video.videoWidth, h = video.videoHeight;
        const sx = Math.floor(w * 0.11), sy = Math.floor(h * 0.08);
        const sw = Math.max(1, w - sx * 2), sh = Math.max(1, h - sy * 2);
        focusCanvas.width = 360;
        focusCanvas.height = Math.max(180, Math.min(640, Math.round(360 * sh / sw)));
        focusContext.drawImage(video, sx, sy, sw, sh, 0, 0, focusCanvas.width, focusCanvas.height);
        count = Math.max(count, faceCountModel.detectForVideo(focusCanvas, timestamp + 1)?.detections?.length || 0);
      } catch (err) {
        // The full-frame models are still valid; focused retry is optional.
        if (now - lastDiagnostic > 15000) console.info('Face focused retry unavailable', err);
      }
    }
    if (!firstFaceFrameAt) firstFaceFrameAt = now;
    if (count > 0) {
      lastPositiveFaceAt = now;
    }
    if (count === 1) {
      lastConfirmedSingleAt = now;
    }
    if (count >= 2) multipleFaceSamples.push(now);
    while (multipleFaceSamples.length && multipleFaceSamples[0] < now - FACE_MULTIPLE_CONFIRM_WINDOW_MS) {
      multipleFaceSamples.shift();
    }
    const multiConfirmed = count >= 2 && multipleFaceSamples.length >= 2;
    const positiveAge = lastPositiveFaceAt ? now - lastPositiveFaceAt : Infinity;
    const initialAge = now - firstFaceFrameAt;
    const stableSingle = count === 1 ||
      (lastConfirmedSingleAt && now - lastConfirmedSingleAt <= FACE_VISIBLE_HOLD_MS);
    // Show a stable signal during brief model misses; do not claim that an
    // absent face is visible forever. Clearly distinguish uncertain detection.
    if (faceOutput) {
      if (multiConfirmed) {
        faceOutput.textContent = `${count} faces in view (confirming)`;
      } else if (stableSingle) {
        faceOutput.textContent = '1 face in view (stabilized)';
      } else if (count >= 2) {
        faceOutput.textContent = 'Possible additional face — verifying';
      } else if (initialAge < FACE_FIRST_SAMPLE_GRACE_MS) {
        faceOutput.textContent = 'Checking camera for a face';
      } else if (lastPositiveFaceAt && positiveAge < 7500) {
        faceOutput.textContent = 'Face signal intermittent — verifying camera';
      } else {
        faceOutput.textContent = 'No face detected in sustained frames';
      }
    }
    if (count === 0 && now - lastDiagnostic > 15000) {
      lastDiagnostic = now;
      console.info('AssignHub no-face diagnostic', {
        sourceWidth:video.videoWidth, sourceHeight:video.videoHeight,
        readyState:video.readyState, countModel:faceCountReady, landmarkModel:faceReady,
        msSinceFace: Number.isFinite(positiveAge) ? Math.round(positiveAge) : null,
      });
    }
    // The existing independent incident duration threshold still applies.
    // An occasional missing frame no longer starts a false NO_FACE episode.
    const absenceCandidate = lastPositiveFaceAt
      ? positiveAge >= FACE_ABSENCE_PRECONFIRM_MS
      : initialAge >= FACE_FIRST_SAMPLE_GRACE_MS;
    if (root.dataset.detectMultiple === 'yes') observe('MULTIPLE_FACES', multiConfirmed, now, undefined, count);
    if (root.dataset.detectAbsence === 'yes') observe('NO_FACE', absenceCandidate, now, undefined, 0);
    if (count !== 1 || landmarks.length !== 1) {
      observe('HEAD_TURNED', false, now);
      return;
    }
    if (root.dataset.detectHead !== 'yes') return;
    const pose = headOffset(landmarks[0]);
    if (!pose) return;
    if (!neutral) { neutral = {yaw:pose.yaw, pitch:pose.pitch}; neutralSamples = 1; return; }
    if (neutralSamples < 12) {
      neutral.yaw = (neutral.yaw * neutralSamples + pose.yaw) / (neutralSamples + 1);
      neutral.pitch = (neutral.pitch * neutralSamples + pose.pitch) / (neutralSamples + 1);
      neutralSamples += 1;
      return;
    }
    const off = Math.abs(pose.yaw - neutral.yaw) > 0.20 || Math.abs(pose.pitch - neutral.pitch) > 0.29;
    observe('HEAD_TURNED', off, now);
  }

  async function assessPhone(now) {
    if ((!phoneReady || !phoneModel) && (!objectPhoneReady || !objectPhoneModel)) return;
    try {
      // Two independent models. This is a verification aid, not proof of phone use.
      let predictions = [];
      if (phoneReady && phoneModel) {
        try {
          predictions = await phoneModel.detect(video, 20, 0.18);
        } catch (error) {
          phoneReady = false;
          if (!phoneError) {phoneError = true; console.warn('COCO-SSD inference interrupted', error);}
        }
      }
      let objectResult = {objects:[], phones:[]};
      let cropResult = {objects:[], phones:[]};
      if (objectPhoneReady && objectPhoneModel) {
        try {
          objectResult = parseObjectPhone(objectPhoneModel.detectForVideo(video, now));
          // One rotating zoomed region per cycle, ONLY when full-frame
          // models found no phone. This assists with oblique/partial objects.
          if (!objectResult.phones.length &&
              !predictions.some(p => isPhoneLabel(p.class)) && phoneCropContext &&
              video.videoWidth >= 200 && video.videoHeight >= 120) {
            const w = video.videoWidth, h = video.videoHeight;
            const fraction = 0.72;
            const sw = Math.round(w * fraction);
            const starts = [0, Math.round((w - sw) / 2), w - sw];
            const sx = starts[phoneCropIndex++ % starts.length];
            phoneCropCanvas.width = 420;
            phoneCropCanvas.height = Math.round(420 * h / sw);
            phoneCropContext.drawImage(video, sx, 0, sw, h, 0, 0, phoneCropCanvas.width, phoneCropCanvas.height);
            cropResult = parseObjectPhone(objectPhoneModel.detectForVideo(phoneCropCanvas, now + 1));
          }
        } catch (error) {
          objectPhoneReady = false;
          if (!objectPhoneError) {objectPhoneError = true; console.warn('EfficientDet inference interrupted', error);}
        }
      }
      const detectedOtherPhones = [...objectResult.phones, ...cropResult.phones];
      const phones = predictions.filter(item => isPhoneLabel(item.class))
                                .sort((a, b) => b.score - a.score);
      const cocoScore = phones.length ? phones[0].score : 0;
      const otherScore = detectedOtherPhones.reduce((best, p) => Math.max(best, p.score), 0);
      const score = Math.max(cocoScore, otherScore);
      const detectorName = otherScore > cocoScore ? 'EfficientDet' : 'COCO-SSD';
      if (score >= PHONE_CONFIRM_SCORE) phonePositiveSamples.push({at:now, score});
      while (phonePositiveSamples.length && phonePositiveSamples[0].at < now - PHONE_CONFIRM_WINDOW_MS)
        phonePositiveSamples.shift();
      // A single positive frame is not sufficient for an incident. Require
      // temporally separated observations to reduce false-positive alerts.
      const distinctSamples = phonePositiveSamples.length >= 2 &&
        phonePositiveSamples[phonePositiveSamples.length - 1].at - phonePositiveSamples[0].at >= 1700;
      const recentPositive = phonePositiveSamples.some(x => now - x.at <= 4400);
      const confirmed = distinctSamples && recentPositive &&
        (score >= PHONE_CONFIRM_SCORE || score >= PHONE_STRONG_SCORE);
      currentPhone = confirmed;
      if (confirmed) lastPhonePresent = now;
      if (phoneOutput) {
        if (confirmed) phoneOutput.textContent = `Possible phone detected (${detectorName}) — needs review`;
        else if (score >= PHONE_CANDIDATE_SCORE)
          phoneOutput.textContent = `Possible phone signal (${detectorName}, ${Math.round(score * 100)}% model confidence) — verifying`;
        else if (lastPhonePresent && now - lastPhonePresent < 4200)
          phoneOutput.textContent = 'Phone signal intermittent — verifying';
        else phoneOutput.textContent = 'No phone detected';
      }
      // Existing duration and server-side review rules remain authoritative.
      observe('PHONE_VISIBLE', confirmed, now, score || undefined);
      // Model diagnostic reports only object labels and numeric scores, never frames.
      if (now - lastPhoneDebugAt >= 12000) {
        lastPhoneDebugAt = now;
        console.info('AssignHub phone diagnostic', {
          model:phoneModelVariant, videoWidth:video.videoWidth, videoHeight:video.videoHeight,
          cellPhoneScores:phones.slice(0, 3).map(p => Number(p.score.toFixed(3))),
          topObjects:predictions.slice(0, 5).map(p => ({label:p.class, score:Number(p.score.toFixed(3))})),
          efficientDetPhoneScores:detectedOtherPhones.slice(0, 3).map(p => Number(p.score.toFixed(3))),
          efficientDetTopObjects:objectResult.objects.slice(0, 5).map(p => ({label:p.label,score:Number(p.score.toFixed(3))})),
          cropPhoneScores:cropResult.phones.slice(0, 3).map(p => Number(p.score.toFixed(3))),
          efficientDetReady:objectPhoneReady,
        });
      }
    } catch (err) {
      if (!phoneError) {phoneError=true; console.warn('Phone inference error', err); send('MONITOR_ERROR', 0);}
      if (phoneOutput) phoneOutput.textContent = 'Phone detector interrupted — technical issue';
    }
  }

  async function loop() {
    if (!active) return;
    // No inference when the browser tab is not visible. The browser monitor logs tab events.
    if (!document.hidden && !processing && video.readyState >= 2 && video.videoWidth > 0 && video.srcObject) {
      processing = true;
      const now = performance.now();
      try {
        if (faceEnabled && now - faceLast >= 850) {faceLast = now; assessFace(now);}
        if (phoneEnabled && now - phoneLast >= 2800) {phoneLast = now; await assessPhone(now);}
      } finally {processing = false;}
    }
    if (!document.hidden && !missingCameraReported && Date.now()-initializedAt > 20000 &&
        (!video.srcObject || video.readyState < 2)) {
      missingCameraReported = true;
      info('AI cannot inspect the webcam. Check camera access; your answers still work.', true);
      send('MONITOR_ERROR', 0);
    }
    if (active) window.setTimeout(loop, 250);
  }

  const stop = () => {
    active = false;
    try {faceModel?.close();} catch (_) {}
    try {faceCountModel?.close();} catch (_) {}
    try {objectPhoneModel?.close();} catch (_) {}
  };
  window.addEventListener('pagehide', stop, {once:true});
  if (!window.isSecureContext) info('AI requires localhost or HTTPS for camera access.', true);
  else info('Loading local AI models. The quiz timer and answers remain independent.');
  Promise.allSettled([faceEnabled ? initFace() : Promise.resolve(),
    phoneEnabled ? Promise.allSettled([initPhone(), initObjectPhone()]) : Promise.resolve()]).then(() => {
    if (!active) return;
    if ((faceEnabled && !faceReady && !faceCountReady) || (phoneEnabled && !phoneReady && !objectPhoneReady))
      info('Some AI models unavailable; the exam continues. Ask your teacher to review technical events.', true);
    else info('AI monitoring active: browser-side inference. No video is uploaded.');
  });
  loop();
})();
