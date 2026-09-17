// CSV export utilities with Shift-JIS encoding support
import Encoding from 'encoding-japanese';

interface ExportData {
  [key: string]: any;
}

export class CSVExporter {
  static formatValue(value: any): string {
    if (value === null || value === undefined) {
      return '';
    }
    if (typeof value === 'string') {
      return `"${value.replace(/"/g, '""')}"`;
    }
    return String(value);
  }

  static generateCSV(headers: string[], data: ExportData[]): string {
    const headerRow = headers.map(h => `"${h}"`).join(',') + '\n';
    const dataRows = data.map(row => {
      return headers.map(header => {
        const value = row[header];
        return this.formatValue(value);
      }).join(',');
    }).join('\n');

    return headerRow + dataRows;
  }

  static async downloadCSV(filename: string, csvContent: string, encoding: 'SJIS' | 'UTF8' = 'SJIS') {
    let blob: Blob;
    if (encoding === 'UTF8') {
      blob = new Blob(['\ufeff' + csvContent], { type: 'text/csv;charset=utf-8;' });
    } else {
      try {
        const bytes = Encoding.convert(csvContent, { to: 'SJIS', from: 'UNICODE', type: 'array' });
        blob = new Blob([new Uint8Array(bytes)], { type: 'text/csv;charset=shift_jis;' });
      } catch (error) {
        console.error('CSV Shift-JIS encoding failed:', error);
        blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
      }
    }
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);
    link.href = url;
    link.download = filename;
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }
}