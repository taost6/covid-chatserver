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

  static async downloadCSV(filename: string, csvContent: string) {
    try {
      console.log('Attempting to encode CSV to Shift-JIS');
      
      // Convert string to Shift_JIS byte array using encoding-japanese
      const sjisArray = Encoding.convert(csvContent, {
        to: 'SJIS',
        from: 'UNICODE',
        type: 'array'
      });

      console.log('Shift-JIS encoding successful, creating blob');
      
      const blob = new Blob([new Uint8Array(sjisArray)], { 
        type: 'text/csv;charset=shift_jis;' 
      });
      
      const link = document.createElement('a');
      const url = URL.createObjectURL(blob);
      link.setAttribute('href', url);
      link.setAttribute('download', filename);
      link.style.visibility = 'hidden';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      
      console.log('CSV download completed with Shift-JIS encoding');
    } catch (error) {
      console.error('CSV Shift-JIS encoding failed:', error);
      console.log('Falling back to UTF-8');
      
      // Fallback to regular UTF-8 download
      const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
      const link = document.createElement('a');
      const url = URL.createObjectURL(blob);
      link.setAttribute('href', url);
      link.setAttribute('download', filename);
      link.style.visibility = 'hidden';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    }
  }
}