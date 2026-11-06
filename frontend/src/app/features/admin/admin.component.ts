import { Component, OnInit, inject, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { apiErrorMessage } from '../../core/http/api-error';
import { LoadStateComponent } from '../../shared/components/load-state/load-state.component';
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
  DemoCleanPreview } from '../../core/services/admin.service';


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
    MatTooltipModule,
    LoadStateComponent
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
  // eslint-disable-next-line @typescript-eslint/prefer-as-const
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
  showResetAllModal = false;
  resetAllPhrase = '';
  resettingAll = false;
  seedingDemo = false;
  seedingTest = false;

  // --- Estados de carregamento/erro das listas do painel ---
  templatesError: string | null = null;
  backupsError: string | null = null;
  backupsLoading = true;
  demoStatusError: string | null = null;
  verifyingBackup: Record<string, boolean> = {};
  backupVerification: Record<string, { valid: boolean; message: string }> = {};
  ngOnInit(): void {
    this.loadTemplates();
    this.loadBackups();
    this.loadDemoStatus();
  }

  // ==========================================
  // WHATSAPP METHODS
  // ==========================================
  // --- Templates Methods ---
  loadTemplates(): void {
    this.loadingTemplates = true;
    this.templatesError = null;
    this.adminService.getWhatsAppTemplates(this.templateCategoryFilter || undefined).subscribe({
      next: (list) => {
        this.templates = list;
        this.loadingTemplates = false;
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.loadingTemplates = false;
        // falha de comunicação não pode parecer "nenhum modelo cadastrado"
        this.templatesError = apiErrorMessage(err, 'Não foi possível carregar os modelos de mensagem.');
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
          this.snackBar.open(apiErrorMessage(err, 'Erro ao atualizar template.'), 'Fechar', { duration: 3500 });
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
          this.snackBar.open(apiErrorMessage(err, 'Erro ao criar template.'), 'Fechar', { duration: 3500 });
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
        this.snackBar.open(apiErrorMessage(err, 'Erro ao excluir template.'), 'Fechar', { duration: 3000 });
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
        const msg = apiErrorMessage(err, 'Erro ao analisar arquivo CSV. Verifique a formatação.');
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
        const msg = apiErrorMessage(err, 'Erro ao processar importação.');
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
        const msg = apiErrorMessage(err, 'Erro ao exportar dados.');
        this.snackBar.open(msg, 'Fechar', { duration: 4000 });
        this.cdr.markForCheck();
      }
    });
  }

  // ==========================================
  // DB BACKUPS METHODS
  // ==========================================
  loadBackups(): void {
    this.backupsLoading = true;
    this.backupsError = null;
    this.adminService.getBackups().subscribe({
      next: (data) => {
        this.backups = data;
        this.backupsLoading = false;
        this.cdr.markForCheck();
      },
      error: (err) => {
        // antes: `error: () => {}` + "Nenhum backup gerado até o momento" — perigoso para quem confia nesta tela
        this.backupsLoading = false;
        this.backupsError = apiErrorMessage(err, 'Não foi possível carregar a lista de backups.');
        this.cdr.markForCheck();
      }
    });
  }

  /** Recalcula o SHA-256 do arquivo no servidor e compara com o registrado. */
  verifyBackup(backup: DbBackup): void {
    this.verifyingBackup = { ...this.verifyingBackup, [backup.id]: true };
    this.adminService.verifyBackup(backup.id).subscribe({
      next: (res) => {
        this.verifyingBackup = { ...this.verifyingBackup, [backup.id]: false };
        const message = !res.exists
          ? res.error || 'Arquivo não encontrado no disco.'
          : res.is_valid
            ? 'Arquivo íntegro (SHA-256 confere). Isto não prova que o backup restaura: teste com `make verify-backup`.'
            : 'ATENÇÃO: o SHA-256 do arquivo NÃO confere com o registrado.';
        this.backupVerification = { ...this.backupVerification, [backup.id]: { valid: res.exists && res.is_valid, message } };
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.verifyingBackup = { ...this.verifyingBackup, [backup.id]: false };
        this.snackBar.open(apiErrorMessage(err, 'Não foi possível verificar o backup.'), 'Fechar', { duration: 5000 });
        this.cdr.markForCheck();
      }
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
        const msg = apiErrorMessage(err, 'Erro ao gerar backup do banco de dados.');
        this.snackBar.open(msg, 'Fechar', { duration: 4500 });
        this.cdr.markForCheck();
      }
    });
  }

  downloadBackupFile(backup: DbBackup, files = false): void {
    const name = files ? backup.files_filename || 'arquivos.tar.gz' : backup.filename;
    const request = files ? this.adminService.downloadBackupFiles(backup.id) : this.adminService.downloadBackup(backup.id);
    request.subscribe({
      next: (blob) => {
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = name;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
        this.snackBar.open(`Download de ${name} iniciado.`, 'OK', { duration: 3000 });
      },
      error: (err) => {
        const msg = apiErrorMessage(err, 'Falha ao baixar arquivo de backup.');
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
        const msg = apiErrorMessage(err, 'Erro ao excluir backup.');
        this.snackBar.open(msg, 'Fechar', { duration: 4000 });
      }
    });
  }

  // ==========================================
  // GESTÃO DE AMBIENTES & DEMONSTRAÇÃO (MOD-01)
  // ==========================================
  loadDemoStatus(): void {
    this.loadingDemoStatus = true;
    this.demoStatusError = null;
    this.adminService.getDemoStatus().subscribe({
      next: (res) => {
        this.demoStatus = res;
        this.loadingDemoStatus = false;
        this.cdr.detectChanges();
      },
      error: (err) => {
        this.loadingDemoStatus = false;
        this.demoStatusError = apiErrorMessage(err, 'Não foi possível ler o modo do sistema (demonstração ou produção).');
        this.cdr.markForCheck();
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
        const msg = apiErrorMessage(err, 'Erro ao carregar prévia de limpeza.');
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
        const msg = apiErrorMessage(err, 'Falha ao executar limpeza de demonstração.');
        this.snackBar.open(msg, 'Fechar', { duration: 6000 });
      }
    });
  }

  openResetAll(): void {
    this.resetAllPhrase = '';
    this.showResetAllModal = true;
  }

  closeResetAll(): void {
    this.showResetAllModal = false;
    this.resetAllPhrase = '';
  }

  executeResetAll(): void {
    if (this.resetAllPhrase.trim().toUpperCase() !== 'ZERAR TODA A BASE') {
      return;
    }
    this.resettingAll = true;
    this.adminService.resetAllData(this.resetAllPhrase.trim()).subscribe({
      next: (res) => {
        this.resettingAll = false;
        this.showResetAllModal = false;
        this.resetAllPhrase = '';
        this.snackBar.open(res.message, 'OK', { duration: 6000 });
        this.loadDemoStatus();
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.resettingAll = false;
        this.snackBar.open(apiErrorMessage(err, 'Não foi possível zerar a base.'), 'Fechar', { duration: 6000 });
        this.cdr.markForCheck();
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
        const msg = apiErrorMessage(err, 'Erro ao recarregar dados demonstrativos.');
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
        const msg = apiErrorMessage(err, 'Erro ao carregar dados de testes/homologação.');
        this.snackBar.open(msg, 'Fechar', { duration: 5000 });
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
