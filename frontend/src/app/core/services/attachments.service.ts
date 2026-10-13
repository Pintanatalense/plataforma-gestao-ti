import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpEvent, HttpRequest } from '@angular/common/http';
import { Observable } from 'rxjs';


export interface Attachment {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  entity_type: string;
  entity_id: string;
  uploaded_by_id: string | null;
  created_at: string;
  updated_at: string;
}

@Injectable({
  providedIn: 'root'
})
export class AttachmentsService {
  private http = inject(HttpClient);
  private apiUrl = '/api/v1/attachments';

  uploadFile(file: File, entityType: string, entityId: string): Observable<HttpEvent<Attachment>> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('entity_type', entityType);
    formData.append('entity_id', entityId);

    const req = new HttpRequest('POST', this.apiUrl, formData, {
      reportProgress: true,
      responseType: 'json'
    });

    return this.http.request(req);
  }

  getAttachments(entityType: string, entityId: string): Observable<Attachment[]> {
    return this.http.get<Attachment[]>(`${this.apiUrl}?entity_type=${entityType}&entity_id=${entityId}`);
  }

  /** Baixa via HttpClient (envia o Bearer) e abre o blob; window.open direto retornaria 401. */
  downloadAttachment(attachmentId: string, filename?: string): void {
    this.http.get(`${this.apiUrl}/${attachmentId}/download`, { responseType: 'blob', observe: 'response' })
      .subscribe({
        next: (res) => {
          const blob = res.body as Blob;
          const url = URL.createObjectURL(blob);
          const type = blob.type || '';
          if (type.includes('pdf') || type.startsWith('image/')) {
            window.open(url, '_blank');
          } else {
            const a = document.createElement('a');
            a.href = url;
            a.download = filename || 'anexo';
            a.click();
          }
          setTimeout(() => URL.revokeObjectURL(url), 60000);
        },
        error: (err) => console.error('Erro ao baixar anexo:', err)
      });
  }

  deleteAttachment(attachmentId: string): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/${attachmentId}`);
  }
  
  formatBytes(bytes: number, decimals = 2) {
    if (!+bytes) return '0 Bytes';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`;
  }
}
