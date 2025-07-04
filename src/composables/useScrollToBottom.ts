import { nextTick } from 'vue';

function easeOutCubic(t: number): number {
  return 1 - Math.pow(1 - t, 3);
}

export function useScrollToBottom() {
  const smoothScrollToBottom = async (element: HTMLElement, duration: number = 400) => {
    await nextTick();
    
    const startScrollTop = element.scrollTop;
    const targetScrollTop = element.scrollHeight - element.clientHeight;
    const distance = targetScrollTop - startScrollTop;
    
    if (distance <= 0) {
      console.log('[Scroll Debug] Already at bottom or no scrollable content');
      return;
    }
    
    const startTime = performance.now();
    
    function animateScroll(currentTime: number) {
      const elapsed = currentTime - startTime;
      const progress = Math.min(elapsed / duration, 1);
      const easeProgress = easeOutCubic(progress);
      
      element.scrollTop = startScrollTop + (distance * easeProgress);
      
      if (progress < 1) {
        requestAnimationFrame(animateScroll);
      } else {
        console.log('[Scroll Debug] Animation completed');
      }
    }
    
    requestAnimationFrame(animateScroll);
  };

  const scrollToBottom = async () => {
    await nextTick();
    console.log('[Scroll Debug] Starting scrollToBottom');
    
    const mainElement = document.querySelector('.v-main') as HTMLElement;
    
    if (mainElement) {
      console.log('[Scroll Debug] Found v-main element');
      await smoothScrollToBottom(mainElement);
      return;
    }
    
    console.log('[Scroll Debug] v-main not found, trying fallbacks');
    
    // Fallbacks
    const fallbacks = [
      'main',
      '.v-application',
      document.documentElement,
      document.body
    ];
    
    for (const selector of fallbacks) {
      const element = typeof selector === 'string' 
        ? document.querySelector(selector) as HTMLElement
        : selector as HTMLElement;
        
      if (element && element.scrollHeight > element.clientHeight) {
        console.log(`[Scroll Debug] Using fallback: ${typeof selector === 'string' ? selector : element.tagName}`);
        await smoothScrollToBottom(element);
        return;
      }
    }
    
    console.log('[Scroll Debug] No scrollable element found');
  };

  return {
    scrollToBottom,
    smoothScrollToBottom
  };
}
