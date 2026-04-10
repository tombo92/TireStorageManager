// TireStorage Manager UI helpers
// - Position size zoom (A-/A+) with persistence (localStorage)
// - Splash screen on first visit per session
// - Licence plate live validator (uppercase + validity indicator only)

// =========================================================
//  German licence-plate validator
// =========================================================
(function () {
  // Matches the same pattern as the Python server-side validator:
  //   1–3 letters (Unterscheidungszeichen)
  //   optional separator (space or hyphen)
  //   1–2 letters (Erkennungsbuchstaben)
  //   optional separator
  //   1–4 digits
  //   optional separator + E or H suffix
  var PLATE_RE = /^[A-ZÄÖÜ]{1,3}[\s\-]?[A-Z]{1,2}[\s\-]?\d{1,4}([\s\-]?[EH])?$/i;

  function validatePlate(value) {
    return PLATE_RE.test(value.trim());
  }

  function initPlateInput() {
    var input = document.getElementById('license_plate');
    if (!input) return;

    var form = input.closest('form');

    // Live: uppercase while typing (preserve caret) + update validity indicator
    input.addEventListener('input', function () {
      var pos   = input.selectionStart;
      var upper = input.value.toUpperCase();
      if (upper !== input.value) {
        input.value = upper;
        input.setSelectionRange(pos, pos);
      }
      updateState(input.value);
    });

    // On blur: only update the validity indicator, never rewrite the value
    input.addEventListener('blur', function () {
      if (input.value.trim()) {
        updateState(input.value);
      }
    });

    // Block form submit if plate is invalid
    if (form) {
      form.addEventListener('submit', function (e) {
        if (input.value.trim() && !validatePlate(input.value)) {
          input.classList.add('is-invalid');
          input.classList.remove('is-valid');
          input.focus();
          e.preventDefault();
        }
      });
    }

    // Show validity indicator for a pre-filled value (edit form)
    if (input.value.trim()) {
      updateState(input.value);
    }

    function updateState(val) {
      if (!val.trim()) {
        input.classList.remove('is-valid', 'is-invalid');
        return;
      }
      if (validatePlate(val)) {
        input.classList.add('is-valid');
        input.classList.remove('is-invalid');
      } else {
        input.classList.add('is-invalid');
        input.classList.remove('is-valid');
      }
    }
  }

  // Also upper-case the confirm_plate field on the delete page
  function initConfirmPlate() {
    var inp = document.getElementById('confirm_plate');
    if (!inp) return;
    inp.addEventListener('input', function () {
      var pos = inp.selectionStart;
      var up  = inp.value.toUpperCase();
      if (up !== inp.value) {
        inp.value = up;
        inp.setSelectionRange(pos, pos);
      }
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    initPlateInput();
    initConfirmPlate();
  });
})();


// =========================================================
//  Splash / Loading Screen (once per browser session)
// =========================================================
(function () {
  const KEY = 'tsm.splashShown';
  const SPLASH_DURATION_MS = 2400;   // matches CSS progress bar animation

  function initSplash() {
    const splash = document.getElementById('splashScreen');
    if (!splash) return;

    // Already shown this session? Remove immediately.
    try {
      if (sessionStorage.getItem(KEY)) {
        splash.remove();
        return;
      }
    } catch (_) { /* private mode – show splash anyway */ }

    // Mark as shown for this session
    try { sessionStorage.setItem(KEY, '1'); } catch (_) {}

    // After the progress bar fills, fade out and remove
    setTimeout(function () {
      splash.classList.add('splash-hidden');
      setTimeout(function () { splash.remove(); }, 700);
    }, SPLASH_DURATION_MS);
  }

  // Run immediately (script is at end of <body>)
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initSplash);
  } else {
    initSplash();
  }
})();

(function () {
  const KEY = "tsm.posZoom";               // 'normal' | '125' | '150'
  const SCALE = { normal: 1.00, "125": 1.15, "150": 1.30 };
  const root = document.documentElement;

  function setScale(mode) {
    const val = SCALE[mode] ?? 1.00;
    root.style.setProperty('--pos-scale', String(val));
    try { localStorage.setItem(KEY, mode); } catch (_) {}
  }
  function getMode() {
    try { return localStorage.getItem(KEY) || 'normal'; } catch (_) { return 'normal'; }
  }

  function initZoomButtons() {
    const minus = document.getElementById('posZoomMinus');
    const plus  = document.getElementById('posZoomPlus');
    if (minus) {
      minus.addEventListener('click', function () {
        const mode = getMode();
        setScale(mode === '150' ? '125' : 'normal');
      });
    }
    if (plus) {
      plus.addEventListener('click', function () {
        const mode = getMode();
        setScale(mode === 'normal' ? '125' : '150');
      });
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    setScale(getMode());
    initZoomButtons();
    initIdleScreensaver();
  });
})();

// =========================================================
//  Idle screensaver – funny car-shop / wheel themed
// =========================================================
(function () {
  const IDLE_MS = 60_000; // 1 minute
  const MAX_SPRITES = 18;
  const SPRITE_INTERVAL_MS = 1200;

  const EMOJIS = [
    '🛞', '🏎️', '🚗', '🔧', '🔩', '⚙️', '🛠️', '🚙', '🚜',
    '🏁', '🧰', '💨', '🪛', '🛻', '🚘', '🚕', '🛣️', '🚦',
    '⛽', '🏗️', '🦺', '🧤', '🪫', '🔋', '🚨', '🐢'
  ];

  const MESSAGES = [
    // Werkstatt-Sprüche
    'Wenn\'s quietscht, braucht\'s Fett!',
    'Schrauben, bis der Arzt kommt!',
    'Gewaltig ist des Schlossers Kraft, wenn er\'s mitm Hebel schafft.',
    'Kommt es aus dem Auspuff schwarz und sauer, läuft der Motor wohl etwas rauer.',
    'Loch an Loch hält doch! Den Rest macht die Farbe.',
    'Nach fest kommt ab.',
    'Ohne Hub, kein Schub!',
    'Ölich, aber fröhlich!',
    'Weiß der Schlosser keinen Rat, nimmt er Hammer oder Draht.',
    'Wenn ich nicht mehr weiter kann, schließ ich Plus an Minus an.',
    'Plus auf Masse, das knallt klasse!',
    'Gesetz der Hebebühne: Runter kommt sie immer!',
    'Stoßgebet eines Schweißers: Gott gebe, dass es klebe!',
    'Es ist nicht alles Golf, was glänzt!',
    // Auto-Witze
    'Warum sind Rennfahrer so cool? Weil sie immer in der Überholspur sind!',
    'Was sagt ein Auto zu seinem Fahrer? Du bringst mich zum Überkochen!',
    'Was ist das wichtigste bei einer Autonummer? Das die Sitze sauber bleiben!',
    'Was macht ein Auto, wenn es dich nicht mag? Es zeigt dir den Auspuff!',
    'Was ist gelb und liegt im Straßengraben? Ein totes Postauto.',
    'Was sagt ein Auto, wenn es müde ist? Ich möchte ins Bett, nicht zur Tankstelle!',
    'Ich bin gegen Rasen auf der Autobahn: Wer soll das denn alles mähen?',
    'Was ist das Lieblingsessen eines Autos? Parkplätzchen!',
    'Mit welchem Auto ist man besonders langsam unterwegs? Mit einem Lahm-Borghini.',
    'Was sagt ein Auto, wenn es durstig ist? Ich brauche eine Tankfüllung!',
    'Was macht ein Auto im Fitnessstudio? Es pumpt seine Reifen auf!',
    'Was sagt ein Auto, wenn es verloren geht? Ich brauche ein GPS!',
    'Was ist der Unterschied zwischen einem Auto und einer Rolle Klopapier? Das Auto kann man gebraucht kaufen.',
    'Warum sind Autos gute Tänzer? Weil sie immer im Rhythmus der Straße tanzen!',
    'Der Geisterfahrer zum Polizisten: "Was heißt hier falsche Richtung? Sie wissen doch gar nicht wohin ich will!"',
    'Polizeihauptwachtmeister Schrullig verwarnt den sündigen Autofahrer: "Ich hoffe, daß ich Sie in Zukunft nicht mehr beim Rasen erwische!" - "Ja. das hoffe ich auch", meint der Autofahrer.',
    'Polizeikontrolle. Der stockbesoffene Fahrer lallt: "Ich hab’ nur Tee getrunken!" Darauf der Polizist: "Dann haben Sie aber mindestens drei Komma null Kamille!"',
    '"Zwanzig Euro gebührenpflichtige Verwarnung", sagt der Polizeibeamte zum Metzgermeister, "oder darf\'s ein wenig mehr sein?"',
    '"Haben Sie das Schild mit der Geschwindigkeitsbegrenzung denn nicht gelesen?" - "Was denn, auch noch lesen bei dem Tempo?',
    'Was ist das Lieblingslied eines Autos? \'Autobahn\' von Kraftwerk!',
    'Was macht ein Auto, wenn es wütend ist? Es lässt Dampf ab!',
    'Zwei Lehrlinge beim Autotest. "Scheinwerfer?" Antwortet der andere "Geht!" - "Rücklicht?" - "Geht!" - "Blinker?" - "Geht! Geht nicht! Geht! Geht nicht!"',
    'Kommst du mit zu Suki gucken ob Hon da ist? Wenn nicht fahrn wir mit zu Bishi.',
    'Verdammt, da hat gerade jemand unser Auto geklaut! - "Mist, konntest du ihn erkennen?" "Nein, aber ich habe mir das Nummernschild gemerkt"',
    'Bei welchem Tier ist das Arschloch vorne? - Bei der Autoschlange',
    'Warum sind Autos immer in Eile? Weil sie immer auf der Überholspur sind!',
    'Was haben 365 benutze Kondome und ein Autoreifen gemeinsam? - It was a Good Year',
    'Warum gehen Autos nie zur Schule? Weil sie schon alles über die Straße wissen!',
    'Was sagt ein Auto, wenn es glücklich ist? Lass uns eine Spritztour machen!',
    'Was macht ein Auto, wenn es dich liebt? Es lässt dich fahren!',
    'Warum liebt das Auto das Radio? Weil es seine Lieblingsmusik immer auf der Fahrt spielt!',
    'Warum ist ein Auto kein guter Koch? Weil es alles aufs Gas stellt!',
    'Was sagt ein Auto, wenn es friert? Schalte die Heizung ein!',
    'Warum sind Autos wie Babys? Wenn sie nicht aufhören zu heulen, stimmt etwas nicht!',
    'Was sagt ein Auto mit Plattfuß? Ich fühle mich runtergefahren!',
    'Was macht ein Auto im Schwimmbad? Es macht den Rückwärtssalto!',
    'Warum hat das Auto einen Stern auf der Motorhaube? Weil es immer im Rampenlicht steht!',
    'Was sagt ein Auto, wenn es neue Reifen braucht? Ich fühle mich abgenutzt!',
    'Was macht ein Auto beim Friseur? Es lässt sich die Reifen schneiden!',
    'Warum werden Autos nie alt? Weil sie immer aufgefrischt werden!',
    'Was sagt ein Auto, wenn es einsam ist? Nehmen wir noch jemanden mit!',
    'Warum ist ein Auto kein guter Zuhörer? Weil es immer über alles hinweggeht!',
    'Was sagt ein Auto, wenn es sich verfährt? Dreh um!',
    'Warum sind Autos schlechte Sänger? Weil sie immer den Ton verfehlen!',
    'Was sagt ein Auto, wenn es den Führerschein sieht? Das ist mein Bild!',
    'Was macht ein Auto im Park? Es lässt die Reifen baumeln!',
    'Warum sind Autos keine guten Gärtner? Weil sie alles platt machen!',
    'Was sagt ein Auto, wenn es müde ist? Schalte mich aus!',
    'Was macht ein Auto auf einer Party? Es dreht auf!',
    'Warum sind Autos gute Seefahrer? Weil sie immer den Kurs halten!',
    'Was sagt ein Auto, wenn es sich freut? Lass uns losfahren!',
    'Warum sind Autos keine guten Versteckspieler? Weil sie immer gefunden werden!',
    'Was sagt ein Auto, wenn es durstig ist? Füll mich auf!',
    'Was macht ein Auto im Kino? Es schaut sich einen Drive-in-Film an!',
    'Warum sind Autos schlechte Schläfer? Weil sie immer auf Touren sind!',
    'Was sagt ein Auto, wenn es gereinigt wird? Ah, das fühlt sich gut an!',
    'Was macht ein Auto auf dem Golfplatz? Es macht einen Drive!',
    'Warum sind Autos keine guten Tänzer? Weil sie immer auf dem Parkplatz stehen!',
    'Was sagt ein Auto, wenn es verkauft wird? Vergiss mich nicht!'
  ];

  const ANIM_CLASSES = ['bounce', 'float', 'spin'];

  let timer = null;
  let spriteTimer = null;
  let overlay = null;
  let msgEl = null;
  let titleEl = null;

  function pick(arr) {
    return arr[Math.floor(Math.random() * arr.length)];
  }
  function rand(min, max) {
    return Math.random() * (max - min) + min;
  }

  function spawnSprite() {
    if (!overlay || !overlay.classList.contains('active')) return;
    // Cap sprite count
    const existing = overlay.querySelectorAll('.idle-sprite');
    if (existing.length >= MAX_SPRITES) {
      existing[0].remove(); // remove oldest
    }

    const el = document.createElement('span');
    el.className = 'idle-sprite ' + pick(ANIM_CLASSES);
    el.textContent = pick(EMOJIS);
    el.style.left = rand(5, 90) + '%';
    el.style.top = rand(5, 85) + '%';
    el.style.fontSize = rand(1.8, 4.5) + 'rem';
    el.style.opacity = rand(0.35, 0.85);
    el.style.setProperty('--dur', rand(3, 10).toFixed(1) + 's');
    el.style.animationDelay = rand(0, 2).toFixed(1) + 's';
    overlay.appendChild(el);
  }

  function showScreensaver() {
    overlay = document.getElementById('idleOverlay');
    msgEl = overlay?.querySelector('.idle-message');
    titleEl = overlay?.querySelector('.idle-title');
    if (!overlay || !msgEl || !titleEl) return;

    // Set app name as the big title
    titleEl.textContent = overlay.dataset.appName || 'Reifenmanager';

    // Pick a random funny message
    msgEl.textContent = pick(MESSAGES);

    // Clear old sprites
    overlay.querySelectorAll('.idle-sprite').forEach(function (s) { s.remove(); });

    overlay.classList.add('active');

    // Immediately spawn a batch, then keep adding
    for (let i = 0; i < 8; i++) {
      setTimeout(spawnSprite, i * 200);
    }
    spriteTimer = setInterval(spawnSprite, SPRITE_INTERVAL_MS);
  }

  function hideScreensaver() {
    if (spriteTimer) { clearInterval(spriteTimer); spriteTimer = null; }
    if (overlay) {
      overlay.classList.remove('active');
      // Clean up sprites after fade-out
      setTimeout(function () {
        if (overlay) overlay.querySelectorAll('.idle-sprite').forEach(function (s) { s.remove(); });
      }, 700);
    }
  }

  function resetTimer() {
    hideScreensaver();
    clearTimeout(timer);
    timer = setTimeout(showScreensaver, IDLE_MS);
  }

  function initIdleScreensaver() {
    ['mousemove', 'mousedown', 'keydown', 'touchstart', 'scroll', 'click'].forEach(function (evt) {
      document.addEventListener(evt, resetTimer, { passive: true });
    });
    timer = setTimeout(showScreensaver, IDLE_MS);
  }

  // Expose for the main IIFE
  window.initIdleScreensaver = initIdleScreensaver;
})();

// =========================================================
//  Update check – AJAX polling on page load + settings page
// =========================================================
(function () {
  var BANNER_DISMISSED_KEY = 'tsm.updateBannerDismissed';

  /**
   * Simple Markdown-to-HTML converter for release notes.
   * Handles: headers, bold, italic, lists, links, line breaks.
   */
  function simpleMarkdown(md) {
    if (!md) return '';
    var html = md
      // Escape HTML entities
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      // Headers (### → <h6>, ## → <h5>)
      .replace(/^### (.+)$/gm, '<h6 class="mt-2 mb-1">$1</h6>')
      .replace(/^## (.+)$/gm, '<h5 class="mt-2 mb-1">$1</h5>')
      // Bold and italic
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.+?)\*/g, '<em>$1</em>')
      // Unordered list items
      .replace(/^[*-] (.+)$/gm, '<li>$1</li>')
      // Links [text](url)
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g,
        '<a href="$2" target="_blank" class="alert-link">$1</a>')
      // Line breaks
      .replace(/\n/g, '<br>');
    // Wrap consecutive <li> in <ul>
    html = html.replace(/((?:<li>.*?<\/li><br>?)+)/g, function (m) {
      return '<ul class="mb-1">' + m.replace(/<br>/g, '') + '</ul>';
    });
    return html;
  }

  function handleUpdateInfo(data) {
    // ── Banner (all pages) ──
    var banner = document.getElementById('updateBanner');
    if (banner && data.update_available) {
      var dismissed = null;
      try { dismissed = sessionStorage.getItem(BANNER_DISMISSED_KEY); } catch (_) {}
      if (dismissed !== data.remote_version) {
        document.getElementById('bannerRemoteVersion').textContent =
          'v' + data.remote_version;
        var autoMsg = document.getElementById('bannerAutoMsg');
        if (autoMsg) {
          autoMsg.textContent = ' Das Update wird beim nächsten Service-Neustart installiert.';
        }
        if (data.release_url) {
          var link = document.getElementById('bannerReleaseLink');
          if (link) {
            link.href = data.release_url;
            link.classList.remove('d-none');
          }
        }
        banner.classList.remove('d-none');
        banner.classList.add('show');
        // When user dismisses, remember for this session+version
        banner.addEventListener('closed.bs.alert', function () {
          try {
            sessionStorage.setItem(BANNER_DISMISSED_KEY, data.remote_version);
          } catch (_) {}
        });
      }
    }

    // ── Settings page elements ──
    var remoteEl = document.getElementById('updateRemoteVersion');
    var upToDateEl = document.getElementById('updateUpToDate');
    var updateNowForm = document.getElementById('updateNowForm');
    var releaseNotesDiv = document.getElementById('updateReleaseNotes');

    if (remoteEl && upToDateEl) {
      if (data.update_available) {
        remoteEl.querySelector('strong').textContent = 'v' + data.remote_version;
        remoteEl.classList.remove('d-none');
        upToDateEl.classList.add('d-none');
        if (updateNowForm) updateNowForm.classList.remove('d-none');
        if (releaseNotesDiv && data.release_notes) {
          releaseNotesDiv.querySelector('.update-release-body').innerHTML =
            simpleMarkdown(data.release_notes);
          releaseNotesDiv.classList.remove('d-none');
        }
      } else if (data.remote_version) {
        remoteEl.classList.add('d-none');
        upToDateEl.classList.remove('d-none');
        if (updateNowForm) updateNowForm.classList.add('d-none');
        if (releaseNotesDiv) releaseNotesDiv.classList.add('d-none');
      }
    }
  }

  function checkForUpdate(forceRefresh) {
    var opts = { method: 'GET' };
    var url = '/api/update-check';

    if (forceRefresh) {
      // POST with CSRF to force cache invalidation
      var csrfMeta = document.querySelector('input[name="_csrf_token"]');
      var token = csrfMeta ? csrfMeta.value : '';
      opts = {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: '_csrf_token=' + encodeURIComponent(token)
      };
    }

    fetch(url, opts)
      .then(function (r) { return r.json(); })
      .then(handleUpdateInfo)
      .catch(function () { /* silent — no network */ });
  }

  document.addEventListener('DOMContentLoaded', function () {
    // Auto-check on every page load (GET, cached server-side)
    checkForUpdate(false);

    // Settings page: "Check now" button forces a fresh fetch
    var btn = document.getElementById('btnCheckUpdate');
    if (btn) {
      btn.addEventListener('click', function () {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Prüfe …';
        // POST forces cache invalidation, then re-fetch
        var csrfInput = document.querySelector('input[name="_csrf_token"]');
        var token = csrfInput ? csrfInput.value : '';
        fetch('/api/update-check', {
          method: 'POST',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
          body: '_csrf_token=' + encodeURIComponent(token)
        })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            handleUpdateInfo(data);
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-search"></i> Jetzt prüfen';
            if (!data.update_available) {
              btn.innerHTML = '<i class="bi bi-check-circle text-success"></i> Aktuell';
              setTimeout(function () {
                btn.innerHTML = '<i class="bi bi-search"></i> Jetzt prüfen';
              }, 3000);
            }
          })
          .catch(function () {
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-search"></i> Jetzt prüfen';
          });
      });
    }
  });
})();

// =========================================================
//  Wheelset list — live search (debounced)
// =========================================================
(function () {
  'use strict';

  var DEBOUNCE_MS = 400;

  document.addEventListener('DOMContentLoaded', function () {
    var input = document.getElementById('wl-search-input');
    var form  = document.getElementById('wl-filter-form');
    if (!input || !form) return;

    var timer = null;

    input.addEventListener('input', function () {
      clearTimeout(timer);
      timer = setTimeout(function () {
        form.submit();
      }, DEBOUNCE_MS);
    });

    // Clear the pending timer if the user submits manually (Enter / button)
    form.addEventListener('submit', function () {
      clearTimeout(timer);
    });
  });
})();
