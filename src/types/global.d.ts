// Global type definitions

declare module 'encoding-japanese' {
  interface ConvertOptions {
    to: string;
    from: string;
    type: string;
  }

  export function convert(data: string, options: ConvertOptions): number[];
}

declare global {
  interface Window {
    Encoding?: {
      convert: (
        data: string,
        options: {
          to: string;
          from: string;
          type: string;
        }
      ) => number[];
    };
  }
}

export {};