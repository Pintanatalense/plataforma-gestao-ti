import { Component, OnInit, inject, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { MatTabsModule } from '@angular/material/tabs';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatTooltipModule } from '@angular/material/tooltip';

import {
  AdminService,
  WhatsAppConfig,
  WhatsAppConfigUpdate,
  CsvAnalysisResponse,
  CsvImportResult,
  DbBackup,
  CsvExportRequest
} from '../../core/services/admin.service';

@Component({
  selector: 'app-admin',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    RouterModule,
    MatTabsModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatSlideToggleModule,
    MatCheckboxModule,
    MatSnackBarModule,
    MatTooltipModule
  ],
  templateUrl: './admin.component.html',
  styleUrls: ['./admin.component.scss']
})
export class AdminComponent implements OnInit {
  private adminService = inject(AdminService);
  private snackBar = inject(MatSnackBar);
  private cdr = inject(ChangeDetectorRef);

  activeTabIndex = 0;
  currentOrigin = typeof window !== 'undefined' ? window.location.origin : 'http://localhost';

  // --- WhatsApp State ---
  loadingWaConfig = false;
  waConfig: WhatsAppConfig = {
    id: '',
    is_active: false,
    provider: 'EVOLUTION_API',
    base_url: 'http://evolution-api:8080',
    api_key_configured: false,
    instance_name: 'gestao_chamados',
    webhook_secret_configured: false,
    updated_at: null
  };
  waApiKeyInput = '';
  waWebhookSecretInput = '';
  testPhone = '';
  testMessage = 'Olá! Esta é uma mensagem de teste da Plataforma de Gestão de TI.';
  testingSend = false;
  testFeedback: { success: boolean; message: string } | null = null;

  // --- CSV Import State ---
  importStep = 1;
  selectedImportEntity = 'categories';
  selectedFile: File | null = null;
  analyzingFile = false;
  analysisResult: CsvAnalysisResponse | null = null;
  importOnDuplicate: 'skip' | 'update' | 'error' = 'skip';
  importDryRun = false;
  executingImport = false;
  importResult: CsvImportResult | null = null;

  // --- CSV Export State ---
  exportEntity: CsvExportRequest['entity_type'] = 'tickets';
  exportDelimiter = ';';
  exportIncludeHeaders = true;
  exportDateFrom = '';
  exportDateTo = '';
  exporting = false;

  // --- DB Backup State ---
  backups: DbBackup[] = [];
  generatingBackup = false;

  ngOnInit(): void {
    this.loadWaConfig();
    this.loadBackups();
  }

  // ==========================================
  // WHATSAPP METHODS
  // ==========================================
  loadWaConfig(): void {
    this.loadingWaConfig = true;
    this.adminService.getWhatsAppConfig().subscribe({
      next: (cfg) => {
        this.waConfig = cfg;
        this.loadingWaConfig = false;
        this.cdr.markForCheck();
      },
      error: () => {
        this.loadingWaConfig = false;
        this.cdr.markForCheck();
      }
    });
  }

  saveWaConfig(): void {
    this.loadingWaConfig = true;
    const updateData: WhatsAppConfigUpdate = {
      is_active: this.waConfig.is_active,
      provider: this.waConfig.provider,
      base_url: this.waConfig.base_url || '',
      instance_name: this.waConfig.instance_name || ''
    };

    if (this.waApiKeyInput) {
      updateData.api_key = this.waApiKeyInput;
    }
    if (this.waWebhookSecretInput) {
      updateData.webhook_secret = this.waWebhookSecretInput;
    }

    this.adminService.updateWhatsAppConfig(updateData).subscribe({
      next: (saved) => {
        this.waConfig = saved;
        this.waApiKeyInput = '';
        this.waWebhookSecretInput = '';
        this.loadingWaConfig = false;
        this.snackBar.open('Configurações do WhatsApp salvas com sucesso!', 'Fechar', { duration: 3500 });
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.loadingWaConfig = false;
        const msg = err.error?.detail || 'Erro ao salvar configurações do WhatsApp';
        this.snackBar.open(msg, 'Fechar', { duration: 4000 });
        this.cdr.markForCheck();
      }
    });
  }

  sendTestWhatsApp(): void {
    if (!this.testPhone) return;
    this.testingSend = true;
    this.testFeedback = null;

    this.adminService.testSendWhatsApp(this.testPhone, this.testMessage).subscribe({
      next: (res) => {
        this.testingSend = false;
        this.testFeedback = { success: true, message: `Mensagem enviada com sucesso: ${res.detail}` };
        this.snackBar.open('Mensagem de teste disparada!', 'OK', { duration: 3500 });
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.testingSend = false;
        const detail = err.error?.detail || err.message || 'Falha ao conectar com o gateway do WhatsApp';
        this.testFeedback = { success: false, message: `Erro no envio: ${detail}` };
        this.cdr.markForCheck();
      }
    });
  }

  // ==========================================
  // CSV IMPORT WIZARD METHODS
  // ==========================================
  onFileSelected(event: any): void {
    const file = event.target.files?.[0];
    if (file) {
      this.selectedFile = file;
      this.cdr.markForCheck();
    }
  }

  analyzeSelectedFile(): void {
    if (!this.selectedFile) return;
    this.analyzingFile = true;

    this.adminService.analyzeCsv(this.selectedFile, this.selectedImportEntity).subscribe({
      next: (analysis) => {
        this.analyzingFile = false;
        this.analysisResult = analysis;
        this.importStep = 2;
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.analyzingFile = false;
        const msg = err.error?.detail || 'Erro ao analisar arquivo CSV. Verifique a formatação.';
        this.snackBar.open(msg, 'Fechar', { duration: 4000 });
        this.cdr.markForCheck();
      }
    });
  }

  executeImport(): void {
    if (!this.analysisResult) return;
    this.executingImport = true;

    this.adminService.executeCsvImport({
      entity_type: this.selectedImportEntity,
      column_mappings: this.analysisResult.column_mappings,
      rows: this.analysisResult.preview_rows,
      on_duplicate: this.importOnDuplicate,
      dry_run: this.importDryRun
    }).subscribe({
      next: (res) => {
        this.executingImport = false;
        this.importResult = res;
        this.importStep = 3;
        this.snackBar.open(`Importação concluída: ${res.success_count} processados com sucesso.`, 'OK', { duration: 4000 });
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.executingImport = false;
        const msg = err.error?.detail || 'Erro ao processar importação.';
        this.snackBar.open(msg, 'Fechar', { duration: 4000 });
        this.cdr.markForCheck();
      }
    });
  }

  resetImportWizard(): void {
    this.importStep = 1;
    this.selectedFile = null;
    this.analysisResult = null;
    this.importResult = null;
    this.cdr.markForCheck();
  }

  // ==========================================
  // CSV EXPORT METHODS
  // ==========================================
  executeExport(): void {
    this.exporting = true;
    const req: CsvExportRequest = {
      entity_type: this.exportEntity,
      delimiter: this.exportDelimiter,
      include_headers: this.exportIncludeHeaders,
      date_from: this.exportDateFrom || null,
      date_to: this.exportDateTo || null
    };

    this.adminService.exportCsv(req).subscribe({
      next: (blob) => {
        this.exporting = false;
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        const now = new Date().toISOString().slice(0, 10);
        a.href = url;
        a.download = `export_${this.exportEntity}_${now}.csv`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
        this.snackBar.open('Arquivo CSV exportado com sucesso!', 'OK', { duration: 3500 });
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.exporting = false;
        const msg = err.error?.detail || 'Erro ao exportar dados.';
        this.snackBar.open(msg, 'Fechar', { duration: 4000 });
        this.cdr.markForCheck();
      }
    });
  }

  // ==========================================
  // DB BACKUPS METHODS
  // ==========================================
  loadBackups(): void {
    this.adminService.getBackups().subscribe({
      next: (data) => {
        this.backups = data;
        this.cdr.markForCheck();
      },
      error: () => {}
    });
  }

  generateBackupNow(): void {
    this.generatingBackup = true;
    this.adminService.generateBackup().subscribe({
      next: (newBackup) => {
        this.generatingBackup = false;
        this.snackBar.open(`Backup gerado com sucesso: ${newBackup.filename}`, 'OK', { duration: 4000 });
        this.loadBackups();
      },
      error: (err) => {
        this.generatingBackup = false;
        const msg = err.error?.detail || 'Erro ao gerar backup do banco de dados.';
        this.snackBar.open(msg, 'Fechar', { duration: 4500 });
        this.cdr.markForCheck();
      }
    });
  }

  downloadBackupFile(backup: DbBackup): void {
    this.adminService.downloadBackup(backup.id).subscribe({
      next: (blob) => {
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = backup.filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
        this.snackBar.open(`Download de ${backup.filename} iniciado.`, 'OK', { duration: 3000 });
      },
      error: (err) => {
        const msg = err.error?.detail || 'Falha ao baixar arquivo de backup.';
        this.snackBar.open(msg, 'Fechar', { duration: 4000 });
      }
    });
  }

  deleteBackupFile(backup: DbBackup): void {
    if (!confirm(`Tem certeza que deseja excluir o backup ${backup.filename}? Esta ação não pode ser desfeita.`)) {
      return;
    }

    this.adminService.deleteBackup(backup.id).subscribe({
      next: () => {
        this.snackBar.open('Backup excluído com sucesso.', 'OK', { duration: 3000 });
        this.loadBackups();
      },
      error: (err) => {
        const msg = err.error?.detail || 'Erro ao excluir backup.';
        this.snackBar.open(msg, 'Fechar', { duration: 4000 });
      }
    });
  }

  // ==========================================
  // HELPERS
  // ==========================================
  formatBytes(bytes: number): string {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  }
}
