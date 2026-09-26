export function generateId(prefix = 'id'): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

export function getTempClass(t: number): string {
  if (t === 0) return 'zero';
  if (t <= 0.3) return 'low';
  if (t <= 0.7) return 'mid';
  return 'high';
}

export function getTempLabel(t: number): string {
  if (t === 0) return 'Deterministic';
  if (t <= 0.3) return 'Grounded';
  if (t <= 0.7) return 'Balanced';
  return 'Hallucination Risk';
}

export function escapeRegex(str: string): string {
  return (str || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export function navigateTo(url: string): void {
  if (typeof window !== 'undefined') {
    window.history.pushState({}, '', url);
    window.dispatchEvent(new PopStateEvent('popstate'));
  }
}

export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    } else {
      const textArea = document.createElement('textarea');
      textArea.value = text;
      textArea.style.position = 'fixed';
      textArea.style.left = '-999999px';
      textArea.style.top = '-999999px';
      document.body.appendChild(textArea);
      textArea.focus();
      textArea.select();
      const successful = document.execCommand('copy');
      textArea.remove();
      return successful;
    }
  } catch (err) {
    console.error('Failed to copy to clipboard', err);
    return false;
  }
}
