/**
 * The browser's full-screen mode, under either of its names: Chrome before 71 -- the 59 of an
 * Android 4.4 tablet among them -- knows only the `webkit` ones. A home-screen app opened full
 * screen by its manifest counts as full screen too, though no element is.
 */

/** The parts of a document this reads, the prefixed ones included. */
type FullscreenDocument = Pick<Document, "addEventListener" | "removeEventListener"> & {
  documentElement: FullscreenElement;
  fullscreenEnabled?: boolean;
  webkitFullscreenEnabled?: boolean;
  fullscreenElement?: Element | null;
  webkitFullscreenElement?: Element | null;
  exitFullscreen?: () => Promise<void>;
  webkitExitFullscreen?: () => void;
  defaultView?: { matchMedia?: (query: string) => { matches: boolean } } | null;
};

type FullscreenElement = {
  requestFullscreen?: () => Promise<void>;
  webkitRequestFullscreen?: () => void;
};

const EVENTS = ["fullscreenchange", "webkitfullscreenchange"];

const page = () => document as unknown as FullscreenDocument;

/** Whether this browser can put a page into full screen at all. */
export function canFullscreen(doc: FullscreenDocument = page()): boolean {
  return Boolean(doc.fullscreenEnabled ?? doc.webkitFullscreenEnabled);
}

/** Whether the page fills the screen: put there, or opened so from a home screen. */
export function isFullscreen(doc: FullscreenDocument = page()): boolean {
  if (doc.fullscreenElement ?? doc.webkitFullscreenElement) return true;
  return Boolean(doc.defaultView?.matchMedia?.("(display-mode: fullscreen)").matches);
}

/** Fill the screen with the page. Only a tap may ask, and a refusal leaves the page as it was. */
export function enterFullscreen(doc: FullscreenDocument = page()): void {
  const root = doc.documentElement;
  try {
    if (root.requestFullscreen) void root.requestFullscreen().catch(() => {});
    else root.webkitRequestFullscreen?.();
  } catch {
    // Refused: the page stays as it is.
  }
}

/** Leave the full screen the page was put in; one opened so from a home screen stays. */
export function exitFullscreen(doc: FullscreenDocument = page()): void {
  if (!(doc.fullscreenElement ?? doc.webkitFullscreenElement)) return;
  if (doc.exitFullscreen) void doc.exitFullscreen().catch(() => {});
  else doc.webkitExitFullscreen?.();
}

/** Call `changed` whenever the page enters or leaves full screen; returns how to stop. */
export function onFullscreenChange(changed: () => void, doc: FullscreenDocument = page()): () => void {
  for (const name of EVENTS) doc.addEventListener(name, changed);
  return () => {
    for (const name of EVENTS) doc.removeEventListener(name, changed);
  };
}
