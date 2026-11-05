import { ChangeDetectorRef, Component, Input, Output, EventEmitter, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { HttpEventType, HttpResponse } from '@angular/common/http';
import { AttachmentsService, Attachment } from '../../../core/services/attachments.service';
import { apiErrorMessage } from '../../../core/http/api-error';

@Component({
  selector: 'app-attachments',
  standalone: true,
  imports: [
    CommonModule,
    MatButtonModule,
    MatIconModule,
    MatProgressBarModule,
    MatSnackBarModule,
    MatTooltipModule
  ],
  template: `
    <div class="attachments-container">
      <div class="attachments-header">
        <h3>Anexos ({{ attachments.length }})</h3>
        
        <input type="file" #fileInput (change)="onFileSelected($event)" style="display: none">
        <div class="upload-actions">
          <label class="restricted-toggle" *ngIf="allowRestricted"
                 matTooltip="Só o setor que atende o chamado vê este anexo; para os demais ele não aparece">
            <input type="checkbox" [checked]="uploadRestricted" (change)="uploadRestricted = $any($event.target).checked"
                   data-testid="attachment-restricted">
            Restrito ao setor
          </label>
          <button mat-stroked-button color="primary" (click)="fileInput.click()" [disabled]="isUploading">
            <mat-icon>upload_file</mat-icon> Anexar Arquivo
          </button>
        </div>
      </div>

      <div *ngIf="loadError" class="attachments-error" role="alert" data-testid="attachments-error"
           style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;padding:10px 14px;border-radius:8px;background:#fef2f2;border:1px solid #fecaca;color:#991b1b;margin-bottom:12px">
        <span style="flex:1 1 220px">{{ loadError }}</span>
        <button mat-stroked-button type="button" data-testid="attachments-retry" (click)="loadAttachments()">Tentar novamente</button>
      </div>

      <div *ngIf="isUploading" class="upload-progress">
        <span>Enviando {{ currentFileName }}... {{ uploadProgress }}%</span>
        <mat-progress-bar mode="determinate" [value]="uploadProgress"></mat-progress-bar>
      </div>

      <div class="attachments-grid" *ngIf="attachments.length > 0">
        <div class="attachment-card" *ngFor="let file of attachments" [class.is-termo]="isTermo(file.filename)">
          <div class="file-icon" [ngClass]="getFileColor(file.content_type)">
            <mat-icon>{{ getFileIcon(file.content_type) }}</mat-icon>
          </div>
          <div class="file-info" (click)="download(file)">
            <div class="file-name-row">
              <span class="file-name" [matTooltip]="file.filename">{{ file.filename }}</span>
              <span class="termo-badge" *ngIf="isTermo(file.filename)">
                <mat-icon>verified</mat-icon> Termo Assinado
              </span>
              <span class="restricted-badge" *ngIf="file.is_internal" matTooltip="Visível só para o setor que atende">
                <mat-icon>lock</mat-icon> Restrito
              </span>
            </div>
            <span class="file-meta">{{ formatBytes(file.size_bytes) }} • {{ file.created_at | date:'dd/MM/yy HH:mm' }}</span>
          </div>
          <button mat-icon-button color="warn" class="delete-btn" (click)="deleteFile(file.id)" matTooltip="Remover anexo">
            <mat-icon>delete</mat-icon>
          </button>
        </div>
      </div>
      
      <div class="empty-state" *ngIf="attachments.length === 0 && !isUploading">
        <mat-icon>attachment</mat-icon>
        <p>Nenhum anexo encontrado. Clique em "Anexar Arquivo" para adicionar.</p>
      </div>
    </div>
  `,
  styles: [`
    .attachments-container {
      margin-top: 16px;
      padding: 16px;
      background: var(--mat-sys-surface-container-lowest);
      border-radius: 12px;
      border: 1px solid var(--mat-sys-outline-variant);
    }

    .attachments-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 16px;
      
      h3 { margin: 0; font-size: 16px; font-weight: 500; }
    }

    .upload-actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }

    .restricted-toggle {
      display: inline-flex; align-items: center; gap: 6px; font-size: 13px; cursor: pointer;
      color: var(--mat-sys-on-surface-variant);
    }

    .restricted-badge {
      display: inline-flex; align-items: center; gap: 3px; background: #fff7ed; color: #c2410c;
      border: 1px solid #fed7aa; border-radius: 12px; font-size: 11px; font-weight: 600; padding: 1px 7px;
      white-space: nowrap;

      mat-icon { font-size: 13px; width: 13px; height: 13px; }
    }

    .upload-progress {
      margin-bottom: 16px;
      padding: 12px;
      background: var(--mat-sys-surface-container);
      border-radius: 8px;
      
      span { display: block; margin-bottom: 8px; font-size: 13px; color: var(--mat-sys-on-surface-variant); }
    }

    .attachments-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
      gap: 12px;
    }

    .attachment-card {
      display: flex;
      align-items: center;
      padding: 12px;
      background: var(--mat-sys-surface);
      border: 1px solid var(--mat-sys-outline-variant);
      border-radius: 8px;
      gap: 12px;
      transition: all 0.2s ease;
      
      &.is-termo {
        border-color: #6ee7b7;
        background: rgba(16, 185, 129, 0.03);
      }

      &:hover {
        border-color: var(--mat-sys-primary);
        box-shadow: 0 2px 8px rgba(0,0,0,0.05);
        
        .delete-btn { opacity: 1; }
      }
    }

    .file-icon {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 40px;
      height: 40px;
      border-radius: 8px;
      background: var(--mat-sys-surface-variant);
      
      &.pdf { color: #d32f2f; background: rgba(211, 47, 47, 0.1); }
      &.image { color: #1976d2; background: rgba(25, 118, 210, 0.1); }
      &.word { color: #0277bd; background: rgba(2, 119, 189, 0.1); }
      &.excel { color: #388e3c; background: rgba(56, 142, 60, 0.1); }
    }

    .file-info {
      flex: 1;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      cursor: pointer;
      
      .file-name-row {
        display: flex;
        align-items: center;
        gap: 8px;
        overflow: hidden;
      }

      .file-name {
        font-weight: 500;
        font-size: 14px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        color: var(--mat-sys-on-surface);
      }

      .termo-badge {
        display: inline-flex;
        align-items: center;
        gap: 3px;
        background: #ecfdf5;
        color: #059669;
        border: 1px solid #a7f3d0;
        border-radius: 12px;
        font-size: 11px;
        font-weight: 600;
        padding: 1px 7px;
        white-space: nowrap;

        mat-icon {
          font-size: 13px;
          width: 13px;
          height: 13px;
        }
      }
      
      .file-meta {
        font-size: 12px;
        color: var(--mat-sys-on-surface-variant);
        margin-top: 2px;
      }
    }

    .delete-btn {
      opacity: 0.3;
      transition: opacity 0.2s;
    }

    .empty-state {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 32px;
      color: var(--mat-sys-on-surface-variant);
      
      mat-icon { font-size: 48px; width: 48px; height: 48px; opacity: 0.5; margin-bottom: 8px; }
      p { margin: 0; font-size: 14px; }
    }
  `]
})
export class AttachmentsComponent implements OnInit {
  @Input() entityType!: string;
  @Input() entityId!: string;
  /** Mostra a opção "Restrito ao setor" (só para quem vê as notas internas do chamado; ADR-026). */
  @Input() allowRestricted = false;
  @Output() attachmentsChange = new EventEmitter<Attachment[]>();

  uploadRestricted = false;

  attachments: Attachment[] = [];
  
  isUploading = false;
  uploadProgress = 0;
  currentFileName = '';

  private attachmentsService = inject(AttachmentsService);
  private snackBar = inject(MatSnackBar);
  private cdr = inject(ChangeDetectorRef);

  /** Falha ao listar: nunca aparece como "Nenhum anexo" (a lista pode existir e não ter sido lida). */
  loadError: string | null = null;

  ngOnInit() {
    this.loadAttachments();
  }

  isTermo(filename: string): boolean {
    const lower = filename.toLowerCase();
    return lower.includes('termo') || lower.includes('cautela') || lower.includes('assinado') || lower.includes('responsabilidade');
  }

  loadAttachments() {
    if (!this.entityType || !this.entityId) return;
    this.loadError = null;
    this.attachmentsService.getAttachments(this.entityType, this.entityId).subscribe({
      next: (data) => {
        this.attachments = data;
        this.attachmentsChange.emit(this.attachments);
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.loadError = apiErrorMessage(err, 'Não foi possível carregar os anexos.');
        this.cdr.markForCheck();
      }
    });
  }

  onFileSelected(event: any) {
    const file: File = event.target.files[0];
    if (file) {
      this.isUploading = true;
      this.uploadProgress = 0;
      this.currentFileName = file.name;
      
      this.attachmentsService.uploadFile(file, this.entityType, this.entityId, this.allowRestricted && this.uploadRestricted).subscribe({
        next: (event: any) => {
          if (event.type === HttpEventType.UploadProgress) {
            this.uploadProgress = Math.round(100 * event.loaded / (event.total || file.size));
          } else if (event instanceof HttpResponse) {
            this.isUploading = false;
            this.snackBar.open('Arquivo enviado com sucesso', 'OK', { duration: 3000 });
            this.loadAttachments();
          }
        },
        error: (err) => {
          this.isUploading = false;
          this.snackBar.open(apiErrorMessage(err, 'Erro ao enviar arquivo'), 'Fechar', { duration: 3000 });
        }
      });
      
      event.target.value = null;
    }
  }

  download(file: Attachment) {
    this.attachmentsService.downloadAttachment(file.id, file.filename);
  }

  deleteFile(id: string) {
    if (confirm('Tem certeza que deseja remover este anexo?')) {
      this.attachmentsService.deleteAttachment(id).subscribe(() => {
        this.snackBar.open('Anexo removido', 'OK', { duration: 3000 });
        this.loadAttachments();
      });
    }
  }

  formatBytes(bytes: number) {
    return this.attachmentsService.formatBytes(bytes);
  }

  getFileIcon(contentType: string): string {
    if (contentType.includes('pdf')) return 'picture_as_pdf';
    if (contentType.includes('image')) return 'image';
    if (contentType.includes('word') || contentType.includes('document')) return 'description';
    if (contentType.includes('excel') || contentType.includes('spreadsheet')) return 'table_chart';
    if (contentType.includes('zip') || contentType.includes('compressed')) return 'folder_zip';
    return 'insert_drive_file';
  }
  
  getFileColor(contentType: string): string {
    if (contentType.includes('pdf')) return 'pdf';
    if (contentType.includes('image')) return 'image';
    if (contentType.includes('word') || contentType.includes('document')) return 'word';
    if (contentType.includes('excel') || contentType.includes('spreadsheet')) return 'excel';
    return '';
  }
}
