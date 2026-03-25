// TireStorage Manager UI helpers
// - Position size zoom (A-/A+) with persistence (localStorage)

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
    'Warum hat der Sportwagen immer Hunger? Weil er ständig aufs Gas drückt!',
    'Was macht ein Auto, wenn es dich nicht mag? Es zeigt dir den Auspuff!',
    'Warum fährt der Rennfahrer nie rückwärts? Weil er Angst vor dem Rückwärtsgang hat!',
    'Was sagt ein Auto, wenn es müde ist? Ich möchte ins Bett, nicht zur Tankstelle!',
    'Warum wurde das Auto rot? Weil es den Gurt sah!',
    'Was ist das Lieblingsessen eines Autos? Parkplatz!',
    'Warum wurde das Auto krank? Es hatte einen Auspuff!',
    'Was sagt ein Auto, wenn es durstig ist? Ich brauche eine Tankfüllung!',
    'Was macht ein Auto im Fitnessstudio? Es pumpt seine Reifen auf!',
    'Was sagt ein Auto, wenn es verloren geht? Ich brauche ein GPS!',
    'Warum sind Autos schlechte Schauspieler? Weil sie immer überfahren!',
    'Warum sind Autos gute Tänzer? Weil sie immer im Rhythmus der Straße tanzen!',
    'Was ist der Lieblingsfilm eines Autos? \'Fast & Furious\'!',
    'Warum gehen Autos nie aus? Weil sie immer einen Schlüssel haben!',
    'Was macht ein Auto, wenn es sich langweilt? Es dreht eine Runde!',
    'Was sagt ein Auto, wenn es zu schnell fährt? Brems dich!',
    'Warum sind Autos so laut? Weil sie immer hupen müssen!',
    'Was ist das Lieblingslied eines Autos? \'Autobahn\' von Kraftwerk!',
    'Was macht ein Auto, wenn es wütend ist? Es lässt Dampf ab!',
    'Warum sind Autos so schlau? Weil sie immer den Weg wissen!',
    'Was sagt ein Auto, wenn es schmutzig ist? Wasch mich!',
    'Was macht ein Auto, wenn es nicht starten will? Es macht eine Pause!',
    'Was sagt ein Auto, wenn es alt wird? Ich brauche ein Update!',
    'Warum sind Autos immer in Eile? Weil sie immer auf der Überholspur sind!',
    'Was ist der Lieblingssport eines Autos? Drag Racing!',
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
