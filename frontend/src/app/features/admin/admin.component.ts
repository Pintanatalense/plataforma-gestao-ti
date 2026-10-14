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
  WhatsAppTemplate,
  WhatsAppOutboxItem,
  WhatsAppOutboxStats,
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
  waActiveSubTab: 'gateway' | 'antiban' | 'templates' | 'outbox' = 'gateway';
  loadingWaConfig = false;
  waConfig: WhatsAppConfig = {
    provider: 'EVOLUTION_API',
    is_enabled: true,
    api_url: 'http://evolution-api:8080',
    instance_name: 'gestao_ti',
    welcome_message: 'Olá! Bem-vindo ao atendimento de TI via WhatsApp.',
    anti_ban_enabled: true,
    min_delay_seconds: 4,
    max_delay_seconds: 10,
    simulate_typing: true,
    typing_duration_seconds: 2,
    max_messages_per_minute: 12,
    cooldown_per_recipient_seconds: 15,
    emergency_pause: false
  };
  waApiKeyInput = '';
  waWebhookSecretInput = '';
  testPhone = '';
  testMessage = 'Olá! Esta é uma mensagem de teste da Plataforma de Gestão de TI.';
  testingSend = false;
  testFeedback: { success: boolean; message: string } | null = null;
  togglingKillSwitch = false;

  // --- WhatsApp Templates State ---
  templates: WhatsAppTemplate[] = [];
  loadingTemplates = false;
  showTemplateModal = false;
  editingTemplateId: string | null = null;
  templateCategoryFilter = '';
  templateForm = {
    name: '',
    code: '',
    category: 'SERVICE_DESK',
    content: '',
    is_active: true
  };
  availableVariables = [
    { tag: '{{solicitante}}', desc: 'Nome do colaborador' },
    { tag: '{{protocolo}}', desc: 'ID do chamado (#12345678)' },
    { tag: '{{titulo}}', desc: 'Título resumido' },
    { tag: '{{status}}', desc: 'Status atual formatado' },
    { tag: '{{prioridade}}', desc: 'Prioridade (Baixa a Crítica)' },
    { tag: '{{atendente}}', desc: 'Técnico responsável' },
    { tag: '{{setor}}', desc: 'Setor de atendimento' },
    { tag: '{{unidade}}', desc: 'Unidade da empresa' },
    { tag: '{{empresa}}', desc: 'Nome da organização' },
    { tag: '{{observacao}}', desc: 'Notas técnicas ou solução' },
    { tag: '{{data}}', desc: 'Data do evento (DD/MM/AAAA)' },
    { tag: '{{hora}}', desc: 'Hora atual (HH:MM)' }
  ];
  savingTemplate = false;

  // --- WhatsApp Outbox State ---
  outboxItems: WhatsAppOutboxItem[] = [];
  outboxStats: WhatsAppOutboxStats | null = null;
  loadingOutbox = false;
  outboxStatusFilter = '';
  processingOutbox = false;


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
    this.loadTemplates();
    this.loadOutboxStats();
    this.loadOutbox();
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
      is_enabled: this.waConfig.is_enabled,
      provider: this.waConfig.provider,
      api_url: this.waConfig.api_url || '',
      instance_name: this.waConfig.instance_name || '',
      welcome_message: this.waConfig.welcome_message || '',
      anti_ban_enabled: this.waConfig.anti_ban_enabled,
      min_delay_seconds: this.waConfig.min_delay_seconds,
      max_delay_seconds: this.waConfig.max_delay_seconds,
      simulate_typing: this.waConfig.simulate_typing,
      typing_duration_seconds: this.waConfig.typing_duration_seconds,
      max_messages_per_minute: this.waConfig.max_messages_per_minute,
      cooldown_per_recipient_seconds: this.waConfig.cooldown_per_recipient_seconds,
      emergency_pause: this.waConfig.emergency_pause
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
        this.snackBar.open('Configurações e parâmetros Anti-Ban salvos com sucesso!', 'Fechar', { duration: 3500 });
        this.loadOutboxStats();
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

  toggleEmergencyPause(): void {
    this.togglingKillSwitch = true;
    this.adminService.toggleEmergencyPause().subscribe({
      next: (res) => {
        this.waConfig.emergency_pause = res.emergency_pause;
        this.togglingKillSwitch = false;
        const msg = res.emergency_pause
          ? 'KILL SWITCH ATIVADO: Todos os disparos da fila foram suspensos preventivamente.'
          : 'Pausa emergencial desativada: Disparos da fila liberados com proteção anti-ban.';
        this.snackBar.open(msg, 'OK', { duration: 4500 });
        this.loadOutboxStats();
        this.cdr.markForCheck();
      },
      error: () => {
        this.togglingKillSwitch = false;
        this.snackBar.open('Erro ao alternar o Kill Switch.', 'Fechar', { duration: 3000 });
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
        this.testFeedback = { success: true, message: `Mensagem enviada com sucesso para ${res.to_phone}!` };
        this.snackBar.open('Mensagem de teste disparada!', 'OK', { duration: 3500 });
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.testingSend = false;
        const detail = err.error?.detail || err.message || 'Falha ao conectar com o gateway do WhatsApp';
        this.testFeedback = { success: false, message: `Erro no envio: ${detail}` };
        this.snackBar.open(`Falha: ${detail}`, 'Fechar', { duration: 4500 });
        this.cdr.markForCheck();
      }
    });
  }

  // --- Templates Methods ---
  loadTemplates(): void {
    this.loadingTemplates = true;
    this.adminService.getWhatsAppTemplates(this.templateCategoryFilter || undefined).subscribe({
      next: (list) => {
        this.templates = list;
        this.loadingTemplates = false;
        this.cdr.markForCheck();
      },
      error: () => {
        this.loadingTemplates = false;
        this.cdr.markForCheck();
      }
    });
  }

  openCreateTemplate(): void {
    this.editingTemplateId = null;
    this.templateForm = {
      name: '',
      code: '',
      category: 'SERVICE_DESK',
      content: '',
      is_active: true
    };
    this.showTemplateModal = true;
  }

  openEditTemplate(tpl: WhatsAppTemplate): void {
    this.editingTemplateId = tpl.id;
    this.templateForm = {
      name: tpl.name,
      code: tpl.code,
      category: tpl.category,
      content: tpl.content,
      is_active: tpl.is_active
    };
    this.showTemplateModal = true;
  }

  closeTemplateModal(): void {
    this.showTemplateModal = false;
    this.editingTemplateId = null;
  }

  insertVariable(varTag: string): void {
    this.templateForm.content = (this.templateForm.content || '') + ' ' + varTag + ' ';
  }

  saveTemplate(): void {
    if (!this.templateForm.name || !this.templateForm.code || !this.templateForm.content) {
      this.snackBar.open('Preencha nome, código e conteúdo do template.', 'OK', { duration: 3000 });
      return;
    }

    this.savingTemplate = true;
    if (this.editingTemplateId) {
      this.adminService.updateWhatsAppTemplate(this.editingTemplateId, this.templateForm).subscribe({
        next: () => {
          this.savingTemplate = false;
          this.showTemplateModal = false;
          this.snackBar.open('Template atualizado com sucesso!', 'OK', { duration: 3000 });
          this.loadTemplates();
        },
        error: (err) => {
          this.savingTemplate = false;
          this.snackBar.open(err.error?.detail || 'Erro ao atualizar template.', 'Fechar', { duration: 3500 });
          this.cdr.markForCheck();
        }
      });
    } else {
      this.adminService.createWhatsAppTemplate(this.templateForm).subscribe({
        next: () => {
          this.savingTemplate = false;
          this.showTemplateModal = false;
          this.snackBar.open('Template cadastrado com sucesso!', 'OK', { duration: 3000 });
          this.loadTemplates();
        },
        error: (err) => {
          this.savingTemplate = false;
          this.snackBar.open(err.error?.detail || 'Erro ao criar template.', 'Fechar', { duration: 3500 });
          this.cdr.markForCheck();
        }
      });
    }
  }

  deleteTemplate(id: string): void {
    if (!confirm('Deseja realmente excluir este template de resposta rápida?')) return;
    this.adminService.deleteWhatsAppTemplate(id).subscribe({
      next: () => {
        this.snackBar.open('Template excluído!', 'OK', { duration: 3000 });
        this.loadTemplates();
      },
      error: (err) => {
        this.snackBar.open(err.error?.detail || 'Erro ao excluir template.', 'Fechar', { duration: 3000 });
      }
    });
  }

  getSimulatedTemplatePreview(content: string): string {
    if (!content) return 'Selecione ou digite um conteúdo para visualizar.';
    let sample = content;
    const samples: Record<string, string> = {
      '{{solicitante}}': 'Carlos Mendes',
      '{{protocolo}}': '#TKT-8492',
      '{{titulo}}': 'Acesso VPN Oscilando',
      '{{status}}': 'Em Atendimento',
      '{{prioridade}}': 'Alta',
      '{{atendente}}': 'Equipe de TI',
      '{{setor}}': 'Infraestrutura',
      '{{unidade}}': 'Matriz Rio',
      '{{empresa}}': 'TechSolutions',
      '{{observacao}}': 'Verificamos as rotas de firewall e o acesso foi normalizado.',
      '{{data}}': '14/10/2026',
      '{{hora}}': '17:30'
    };
    for (const [k, v] of Object.entries(samples)) {
      sample = sample.split(k).join(v);
    }
    return sample;
  }

  // --- Outbox Queue Methods ---
  loadOutbox(): void {
    this.loadingOutbox = true;
    this.adminService.getWhatsAppOutbox(this.outboxStatusFilter || undefined).subscribe({
      next: (items) => {
        this.outboxItems = items;
        this.loadingOutbox = false;
        this.cdr.markForCheck();
      },
      error: () => {
        this.loadingOutbox = false;
        this.cdr.markForCheck();
      }
    });
  }

  loadOutboxStats(): void {
    this.adminService.getWhatsAppOutboxStats().subscribe({
      next: (stats) => {
        this.outboxStats = stats;
        this.cdr.markForCheck();
      }
    });
  }

  processOutboxNow(): void {
    this.processingOutbox = true;
    this.adminService.processWhatsAppOutbox(15).subscribe({
      next: (res) => {
        this.processingOutbox = false;
        this.snackBar.open(res.message, 'OK', { duration: 4000 });
        this.loadOutbox();
        this.loadOutboxStats();
      },
      error: (err) => {
        this.processingOutbox = false;
        this.snackBar.open(err.error?.detail || 'Erro ao processar fila.', 'Fechar', { duration: 3500 });
        this.cdr.markForCheck();
      }
    });
  }

  cancelOutboxItem(id: string): void {
    this.adminService.cancelWhatsAppOutboxItem(id).subscribe({
      next: () => {
        this.snackBar.open('Envio cancelado.', 'OK', { duration: 2500 });
        this.loadOutbox();
        this.loadOutboxStats();
      },
      error: () => {
        this.snackBar.open('Não foi possível cancelar este item.', 'Fechar', { duration: 3000 });
      }
    });
  }

  retryOutboxItem(id: string): void {
    this.adminService.retryWhatsAppOutboxItem(id).subscribe({
      next: () => {
        this.snackBar.open('Item reagendado na fila!', 'OK', { duration: 2500 });
        this.loadOutbox();
        this.loadOutboxStats();
      },
      error: () => {
        this.snackBar.open('Não foi possível reagendar este item.', 'Fechar', { duration: 3000 });
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
