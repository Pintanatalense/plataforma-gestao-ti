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
  WhatsAppTemplate,
  CsvAnalysisResponse,
  CsvImportResult,
  DbBackup,
  CsvExportRequest,
  DemoStatus,
  DemoCleanPreview,
  SmtpConfig
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

  // --- WhatsApp: respostas rápidas (o canal em si fica em Notificações > Entregas e regras) ---
  waActiveSubTab: 'templates' = 'templates';
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

  // --- Gestão de Ambientes & Demonstração (MOD-01) ---
  demoStatus: DemoStatus | null = null;
  loadingDemoStatus = false;
  cleanPreview: DemoCleanPreview | null = null;
  loadingCleanPreview = false;
  showCleanConfirmModal = false;
  cleanConfirmationPhrase = '';
  cleaningDemo = false;
  seedingDemo = false;
  seedingTest = false;

  // --- Notificações por E-mail / SMTP (MOD-11) ---
  smtpConfig: SmtpConfig = {
    is_enabled: false,
    host: 'smtp.gmail.com',
    port: 587,
    security: 'STARTTLS',
    username: '',
    from_email: 'suporte@empresa.com.br',
    from_name: 'Service Desk Central',
    app_base_url: 'http://localhost'
  };
  smtpPasswordInput = '';
  loadingSmtpConfig = false;
  savingSmtpConfig = false;
  testSmtpEmail = '';
  testingSmtp = false;
  smtpTestFeedback: { success: boolean; message: string } | null = null;

  ngOnInit(): void {
    this.loadTemplates();
    this.loadBackups();
    this.loadDemoStatus();
    this.loadSmtpConfig();
  }

  // ==========================================
  // WHATSAPP METHODS
  // ==========================================
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
  // GESTÃO DE AMBIENTES & DEMONSTRAÇÃO (MOD-01)
  // ==========================================
  loadDemoStatus(): void {
    this.loadingDemoStatus = true;
    this.adminService.getDemoStatus().subscribe({
      next: (res) => {
        this.demoStatus = res;
        this.loadingDemoStatus = false;
        this.cdr.detectChanges();
      },
      error: () => {
        this.loadingDemoStatus = false;
      }
    });
  }

  openCleanPreview(): void {
    this.loadingCleanPreview = true;
    this.cleanConfirmationPhrase = '';
    this.adminService.previewDemoClean().subscribe({
      next: (res) => {
        this.cleanPreview = res;
        this.loadingCleanPreview = false;
        this.showCleanConfirmModal = true;
        this.cdr.detectChanges();
      },
      error: (err) => {
        this.loadingCleanPreview = false;
        const msg = err.error?.detail || 'Erro ao carregar prévia de limpeza.';
        this.snackBar.open(msg, 'Fechar', { duration: 4000 });
      }
    });
  }

  closeCleanModal(): void {
    this.showCleanConfirmModal = false;
    this.cleanConfirmationPhrase = '';
  }

  executeCleanDemo(): void {
    if (this.cleanConfirmationPhrase.trim() !== 'LIMPAR DADOS DE DEMONSTRACAO') {
      this.snackBar.open('Frase de confirmação incorreta. Digite exatamente: LIMPAR DADOS DE DEMONSTRACAO', 'OK', { duration: 4000 });
      return;
    }

    this.cleaningDemo = true;
    this.adminService.cleanDemoData(this.cleanConfirmationPhrase.trim()).subscribe({
      next: (res) => {
        this.cleaningDemo = false;
        this.showCleanConfirmModal = false;
        this.snackBar.open(`Limpeza concluída! ${res.message}`, 'OK', { duration: 5000 });
        this.loadDemoStatus();
      },
      error: (err) => {
        this.cleaningDemo = false;
        const msg = err.error?.detail || 'Falha ao executar limpeza de demonstração.';
        this.snackBar.open(msg, 'Fechar', { duration: 6000 });
      }
    });
  }

  executeSeedDemo(): void {
    if (!confirm('Deseja recarregar o conjunto modelo de dados demonstrativos?')) {
      return;
    }
    this.seedingDemo = true;
    this.adminService.seedDemoData().subscribe({
      next: (res) => {
        this.seedingDemo = false;
        this.snackBar.open('Dados demonstrativos recarregados com sucesso!', 'OK', { duration: 4000 });
        this.loadDemoStatus();
      },
      error: (err) => {
        this.seedingDemo = false;
        const msg = err.error?.detail || 'Erro ao recarregar dados demonstrativos.';
        this.snackBar.open(msg, 'Fechar', { duration: 4000 });
      }
    });
  }

  executeSeedTest(): void {
    if (!confirm('Deseja popular a base com os dados completos de testes/homologação (QA)?')) {
      return;
    }
    this.seedingTest = true;
    this.adminService.seedTestData().subscribe({
      next: (res) => {
        this.seedingTest = false;
        this.snackBar.open(res.message || 'Base de testes/homologação carregada com sucesso!', 'OK', { duration: 5000 });
        this.loadDemoStatus();
      },
      error: (err) => {
        this.seedingTest = false;
        const msg = err.error?.detail || 'Erro ao carregar dados de testes/homologação.';
        this.snackBar.open(msg, 'Fechar', { duration: 5000 });
      }
    });
  }

  // ==========================================
  // NOTIFICAÇÕES POR E-MAIL / SMTP (MOD-11)
  // ==========================================
  loadSmtpConfig(): void {
    this.loadingSmtpConfig = true;
    this.adminService.getSmtpConfig().subscribe({
      next: (cfg) => {
        this.smtpConfig = cfg;
        this.smtpPasswordInput = cfg.password || '';
        this.loadingSmtpConfig = false;
        this.cdr.detectChanges();
      },
      error: () => {
        this.loadingSmtpConfig = false;
      }
    });
  }

  saveSmtpConfig(): void {
    this.savingSmtpConfig = true;
    const payload: SmtpConfig = {
      ...this.smtpConfig,
      password: this.smtpPasswordInput ? this.smtpPasswordInput : undefined
    };
    this.adminService.updateSmtpConfig(payload).subscribe({
      next: (cfg) => {
        this.smtpConfig = cfg;
        this.smtpPasswordInput = cfg.password || '********';
        this.savingSmtpConfig = false;
        this.snackBar.open('Configurações de SMTP salvas com sucesso!', 'OK', { duration: 3000 });
      },
      error: (err) => {
        this.savingSmtpConfig = false;
        const msg = err.error?.detail || 'Erro ao salvar configuração SMTP.';
        this.snackBar.open(msg, 'Fechar', { duration: 4000 });
      }
    });
  }

  runSmtpTest(): void {
    if (!this.testSmtpEmail || !this.testSmtpEmail.includes('@')) {
      this.snackBar.open('Informe um e-mail de destino válido para o teste.', 'OK', { duration: 3000 });
      return;
    }
    this.testingSmtp = true;
    this.smtpTestFeedback = null;
    this.adminService.testSmtpConnection({
      target_email: this.testSmtpEmail,
      host: this.smtpConfig.host,
      port: this.smtpConfig.port,
      security: this.smtpConfig.security,
      username: this.smtpConfig.username,
      password: this.smtpPasswordInput && this.smtpPasswordInput !== '********' ? this.smtpPasswordInput : undefined,
      from_email: this.smtpConfig.from_email,
      from_name: this.smtpConfig.from_name
    }).subscribe({
      next: (res) => {
        this.testingSmtp = false;
        this.smtpTestFeedback = { success: true, message: `E-mail de teste enviado com sucesso para ${res.target_email}!` };
      },
      error: (err) => {
        this.testingSmtp = false;
        const msg = err.error?.detail || 'Falha na conexão SMTP.';
        this.smtpTestFeedback = { success: false, message: msg };
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
