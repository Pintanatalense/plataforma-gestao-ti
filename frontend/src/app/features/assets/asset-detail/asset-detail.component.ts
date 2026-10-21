import { Component, OnInit, ViewChild, inject, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterModule } from '@angular/router';
import { FormsModule, ReactiveFormsModule, FormBuilder, FormGroup, Validators } from '@angular/forms';
import { MatTabsModule } from '@angular/material/tabs';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { HttpEventType, HttpResponse } from '@angular/common/http';

import { Asset, AssetMovement, AssetService } from '../../../core/services/asset.service';
import { Employee, OrganizationService, Unit } from '../../../core/services/organization.service';
import { AttachmentsService, Attachment } from '../../../core/services/attachments.service';
import { AttachmentsComponent } from '../../../shared/components/attachments/attachments.component';

@Component({
  selector: 'app-asset-detail',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    FormsModule,
    ReactiveFormsModule,
    MatTabsModule,
    MatButtonModule,
    MatIconModule,
    MatSnackBarModule,
    MatTooltipModule,
    MatProgressBarModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    AttachmentsComponent
  ],
  templateUrl: './asset-detail.component.html',
  styleUrls: ['./asset-detail.component.scss']
})
export class AssetDetailComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private assetService = inject(AssetService);
  private orgService = inject(OrganizationService);
  private attachmentsService = inject(AttachmentsService);
  private snackBar = inject(MatSnackBar);
  private fb = inject(FormBuilder);
  private cdr = inject(ChangeDetectorRef);

  @ViewChild('attachmentsComp') attachmentsComp?: AttachmentsComponent;

  asset: Asset | null = null;
  movements: AssetMovement[] = [];
  specEntries: [string, any][] = [];

  units: Unit[] = [];
  employees: Employee[] = [];
  attachments: Attachment[] = [];
  tickets: any[] = [];
  isLoadingTickets = false;

  isLoading = true;
  errorMessage = '';

  isUploadingStatement = false;
  uploadProgress = 0;

  // Action Modals State
  activeModal: 'reserve' | 'deliver' | 'return' | 'inspect' | null = null;
  actionForm: FormGroup = this.fb.group({
    employee_id: [''],
    notes: [''],
    send_to_maintenance: [false]
  });

  ngOnInit(): void {
    const initialId = this.route.snapshot.paramMap.get('id');
    if (initialId) {
      this.loadAsset(initialId);
      this.loadMovements(initialId);
      this.loadAttachments(initialId);
      this.loadTickets(initialId);
    }

    this.route.paramMap.subscribe((params) => {
      const assetId = params.get('id');
      if (assetId && assetId !== this.asset?.id) {
        this.loadAsset(assetId);
        this.loadMovements(assetId);
        this.loadAttachments(assetId);
        this.loadTickets(assetId);
      }
    });

    this.loadDependencies();
  }

  loadAsset(id: string): void {
    this.isLoading = true;
    this.errorMessage = '';
    this.cdr.markForCheck();

    this.assetService.getAsset(id).subscribe({
      next: (asset) => {
        this.asset = asset;
        this.specEntries = asset.technical_specs ? Object.entries(asset.technical_specs) : [];
        this.isLoading = false;
        this.cdr.detectChanges();
      },
      error: (err) => {
        console.error('Erro ao carregar ativo:', err);
        this.errorMessage = 'Não foi possível carregar os detalhes do ativo. Verifique se o equipamento existe ou tente novamente.';
        this.isLoading = false;
        this.cdr.detectChanges();
      }
    });
  }

  loadMovements(id: string): void {
    this.assetService.getMovementsByAsset(id).subscribe({
      next: (movs) => {
        this.movements = movs || [];
        this.cdr.markForCheck();
      },
      error: (err) => console.error('Erro ao carregar movimentações:', err)
    });
  }

  loadAttachments(id?: string): void {
    const assetId = id || this.asset?.id;
    if (!assetId) return;
    this.attachmentsService.getAttachments('ASSET', assetId).subscribe({
      next: (atts) => {
        this.attachments = atts || [];
        this.cdr.markForCheck();
      },
      error: (err) => console.error('Erro ao carregar anexos do ativo:', err)
    });
  }

  loadTickets(id?: string): void {
    const assetId = id || this.asset?.id;
    if (!assetId) return;
    this.isLoadingTickets = true;
    this.assetService.getAssetTickets(assetId).subscribe({
      next: (tickets) => {
        this.tickets = tickets || [];
        this.isLoadingTickets = false;
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.isLoadingTickets = false;
        console.error('Erro ao carregar chamados do ativo:', err);
      }
    });
  }

  onAttachmentsChanged(atts: Attachment[]): void {
    this.attachments = atts || [];
    this.cdr.markForCheck();
  }

  get hasSignedStatement(): boolean {
    return !!this.signedStatementFile;
  }

  get signedStatementFile(): Attachment | undefined {
    if (!this.attachments || this.attachments.length === 0) return undefined;
    const byKeyword = this.attachments.find((att) => {
      const name = att.filename.toLowerCase();
      return (
        name.includes('termo') ||
        name.includes('cautela') ||
        name.includes('assinado') ||
        name.includes('responsabilidade')
      );
    });
    if (byKeyword) return byKeyword;
    return this.attachments.find((att) => att.filename.toLowerCase().endsWith('.pdf'));
  }

  onUploadStatementFile(event: any): void {
    const file: File = event.target.files?.[0];
    if (!file || !this.asset) return;

    this.isUploadingStatement = true;
    this.uploadProgress = 0;
    this.cdr.markForCheck();

    this.attachmentsService.uploadFile(file, 'ASSET', this.asset.id).subscribe({
      next: (httpEvent: any) => {
        if (httpEvent.type === HttpEventType.UploadProgress) {
          this.uploadProgress = Math.round((100 * httpEvent.loaded) / (httpEvent.total || file.size));
          this.cdr.markForCheck();
        } else if (httpEvent instanceof HttpResponse) {
          this.isUploadingStatement = false;
          this.snackBar.open('Termo assinado anexado com sucesso ao ativo!', 'OK', { duration: 3500 });
          this.loadAttachments();
          if (this.attachmentsComp) {
            this.attachmentsComp.loadAttachments();
          }
          this.cdr.detectChanges();
        }
      },
      error: (err) => {
        this.isUploadingStatement = false;
        this.snackBar.open(err.error?.detail || err.error?.error?.message || 'Erro ao anexar termo assinado', 'Fechar', { duration: 4000 });
        this.cdr.detectChanges();
      }
    });

    event.target.value = null;
  }

  downloadAttachment(attachment: Attachment): void {
    this.attachmentsService.downloadAttachment(attachment.id, attachment.filename);
  }

  loadDependencies(): void {
    this.orgService.getUnits().subscribe({
      next: (units) => {
        this.units = units || [];
        this.cdr.markForCheck();
      },
      error: () => {}
    });

    this.orgService.getEmployees().subscribe({
      next: (emps) => {
        this.employees = emps || [];
        this.cdr.markForCheck();
      },
      error: () => {}
    });
  }

  get displayedUnitName(): string {
    if (this.asset?.unit?.name) {
      const code = this.asset.unit.code ? ` (${this.asset.unit.code})` : '';
      return `${this.asset.unit.name}${code}`;
    }
    if (!this.asset?.unit_id) return 'Não definida';
    const found = this.units?.find((u) => u.id === this.asset?.unit_id);
    return found ? `${found.name} (${found.code})` : 'Unidade Cadastrada';
  }

  get displayedEmployeeName(): string {
    if (this.asset?.employee?.name) {
      const reg = this.asset.employee.registration_number ? ` (Matrícula: ${this.asset.employee.registration_number})` : '';
      const pos = this.asset.employee.position ? ` — ${this.asset.employee.position}` : '';
      return `${this.asset.employee.name}${reg}${pos}`;
    }
    if (this.asset?.employee_id) {
      const found = this.employees?.find((e) => e.id === this.asset?.employee_id);
      return found ? `${found.name} (${found.registration})` : 'Colaborador Vinculado';
    }
    return 'Nenhum (Disponível em Estoque)';
  }

  getUnitName(unitId?: string): string {
    if (!unitId) return 'N/A';
    const found = this.units?.find((u) => u.id === unitId);
    return found ? found.name : 'N/A';
  }

  getEmployeeName(employeeId?: string | null): string {
    if (!employeeId) return 'Nenhum (Em Estoque)';
    const found = this.employees?.find((e) => e.id === employeeId);
    return found ? `${found.name} (${found.registration})` : 'Colaborador';
  }

  getSpecLabel(key: string): string {
    const schema = this.asset?.category?.spec_schema;
    if (schema && schema[key]?.label) {
      return schema[key].label;
    }
    const map: Record<string, string> = {
      cpu: 'Processador (CPU)',
      ram: 'Memória RAM',
      storage: 'Armazenamento / Disco',
      os: 'Sistema Operacional',
      tela: 'Tamanho da Tela',
      imei: 'IMEI / Registro',
      tipo: 'Tecnologia / Tipo',
      conexao: 'Interfaces de Conexão',
      resolucao: 'Resolução Máxima',
      velocidade: 'Velocidade de Impressão',
      cor: 'Cor / Acabamento',
      voltagem: 'Tensão / Voltagem',
      potencia: 'Potência / Consumo',
      mac_address: 'Endereço MAC',
      hostname: 'Nome de Rede (Hostname)',
      last_logged_user: 'Último Usuário Conectado'
    };
    return map[key.toLowerCase()] || key.replace(/_/g, ' ').toUpperCase();
  }

  getSpecIcon(key: string): string {
    const k = key.toLowerCase();
    if (k.includes('cpu') || k.includes('proc')) return 'memory';
    if (k.includes('ram') || k.includes('mem')) return 'speed';
    if (k.includes('storage') || k.includes('armazenamento') || k.includes('ssd') || k.includes('hd')) return 'dns';
    if (k.includes('os') || k.includes('sistema')) return 'terminal';
    if (k.includes('tela') || k.includes('screen') || k.includes('display')) return 'laptop';
    if (k.includes('imei') || k.includes('serial')) return 'fingerprint';
    if (k.includes('mac') || k.includes('hostname') || k.includes('rede')) return 'lan';
    if (k.includes('usuario') || k.includes('user')) return 'person';
    if (k.includes('conex') || k.includes('porta') || k.includes('usb')) return 'cable';
    if (k.includes('tipo') || k.includes('print')) return 'print';
    if (k.includes('resol')) return 'aspect_ratio';
    if (k.includes('vel')) return 'speed';
    return 'settings_input_component';
  }

  get isWarrantyActive(): boolean {
    if (!this.asset?.warranty_expires) return false;
    try {
      const exp = new Date(this.asset.warranty_expires);
      if (isNaN(exp.getTime())) return false;
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      return exp >= today;
    } catch {
      return false;
    }
  }

  get warrantyDaysRemaining(): number | null {
    if (!this.asset?.warranty_expires) return null;
    try {
      const exp = new Date(this.asset.warranty_expires).getTime();
      if (isNaN(exp)) return null;
      const today = new Date().setHours(0, 0, 0, 0);
      const diffDays = Math.ceil((exp - today) / (1000 * 60 * 60 * 24));
      return diffDays;
    } catch {
      return null;
    }
  }

  getStatusBadgeClass(status?: string): string {
    switch (status) {
      case 'IN_STOCK':
        return 'status-in_stock';
      case 'RESERVED':
        return 'status-reserved';
      case 'IN_USE':
        return 'status-in_use';
      case 'PENDING_INSPECTION':
        return 'status-pending_inspection';
      case 'MAINTENANCE':
        return 'status-maintenance';
      case 'DECOMMISSIONED':
        return 'status-decommissioned';
      default:
        return 'status-default';
    }
  }

  getStatusLabel(status?: string): string {
    switch (status) {
      case 'IN_STOCK':
        return 'Em Estoque';
      case 'RESERVED':
        return 'Reservado';
      case 'IN_USE':
        return 'Em Uso';
      case 'PENDING_INSPECTION':
        return 'Aguardando Inspeção';
      case 'MAINTENANCE':
        return 'Em Manutenção';
      case 'DECOMMISSIONED':
        return 'Baixado / Desativado';
      default:
        return status || 'Desconhecido';
    }
  }

  getTicketStatusLabel(status: string): string {
    const map: Record<string, string> = {
      OPENED: 'Aberto',
      IN_PROGRESS: 'Em Atendimento',
      PENDING: 'Pendente',
      RESOLVED: 'Resolvido',
      CLOSED: 'Encerrado'
    };
    return map[status] || status;
  }

  getTicketStatusBadgeClass(status: string): string {
    switch (status) {
      case 'OPENED': return 'ticket-opened';
      case 'IN_PROGRESS': return 'ticket-in_progress';
      case 'PENDING': return 'ticket-pending';
      case 'RESOLVED': return 'ticket-resolved';
      case 'CLOSED': return 'ticket-closed';
      default: return 'ticket-default';
    }
  }

  getPriorityLabel(priority: string): string {
    const map: Record<string, string> = {
      LOW: 'Baixa',
      MEDIUM: 'Média',
      HIGH: 'Alta',
      CRITICAL: 'Crítica'
    };
    return map[priority] || priority;
  }

  getPriorityBadgeClass(priority: string): string {
    return `priority-${priority?.toLowerCase() || 'low'}`;
  }

  printResponsibilityStatement(): void {
    if (!this.asset) return;
    this.assetService.openResponsibilityStatement(this.asset.id);
  }

  // =========================================================================
  // Lifecycle Actions
  // =========================================================================

  openModal(type: 'reserve' | 'deliver' | 'return' | 'inspect'): void {
    this.activeModal = type;
    this.actionForm.reset({
      employee_id: this.asset?.employee_id || '',
      notes: '',
      send_to_maintenance: false
    });
  }

  closeModal(): void {
    this.activeModal = null;
  }

  confirmReserve(): void {
    if (!this.asset) return;
    const { employee_id, notes } = this.actionForm.value;
    this.assetService.reserveAsset(this.asset.id, { employee_id, notes }).subscribe({
      next: () => {
        this.snackBar.open('Ativo reservado com sucesso!', 'OK', { duration: 3000 });
        this.closeModal();
        this.refreshData();
      },
      error: (err) => this.showError(err)
    });
  }

  confirmCancelReservation(): void {
    if (!this.asset) return;
    this.assetService.cancelReservation(this.asset.id).subscribe({
      next: () => {
        this.snackBar.open('Reserva cancelada. Ativo voltou para o estoque.', 'OK', { duration: 3000 });
        this.refreshData();
      },
      error: (err) => this.showError(err)
    });
  }

  confirmDeliver(): void {
    if (!this.asset) return;
    const { employee_id, notes } = this.actionForm.value;
    if (!employee_id) {
      this.snackBar.open('Selecione o colaborador que receberá o ativo.', 'OK', { duration: 3500 });
      return;
    }
    this.assetService.deliverAsset(this.asset.id, { employee_id, notes }).subscribe({
      next: () => {
        this.snackBar.open('Ativo entregue ao colaborador com sucesso!', 'OK', { duration: 3000 });
        this.closeModal();
        this.refreshData();
      },
      error: (err) => this.showError(err)
    });
  }

  confirmReturn(): void {
    if (!this.asset) return;
    const { notes } = this.actionForm.value;
    this.assetService.returnAsset(this.asset.id, { notes }).subscribe({
      next: () => {
        this.snackBar.open('Devolução registrada. O ativo está agora aguardando inspeção técnica.', 'OK', { duration: 3500 });
        this.closeModal();
        this.refreshData();
      },
      error: (err) => this.showError(err)
    });
  }

  confirmInspect(approved: boolean): void {
    if (!this.asset) return;
    const { notes, send_to_maintenance } = this.actionForm.value;
    this.assetService.inspectAsset(this.asset.id, {
      approved,
      send_to_maintenance: !approved || send_to_maintenance,
      notes
    }).subscribe({
      next: () => {
        const msg = approved
          ? 'Inspeção aprovada! Equipamento liberado para estoque.'
          : 'Equipamento reprovado na inspeção e encaminhado para manutenção.';
        this.snackBar.open(msg, 'OK', { duration: 3500 });
        this.closeModal();
        this.refreshData();
      },
      error: (err) => this.showError(err)
    });
  }

  private refreshData(): void {
    if (this.asset) {
      this.loadAsset(this.asset.id);
      this.loadMovements(this.asset.id);
    }
  }

  private showError(err: any): void {
    const msg = err.error?.error?.message || err.error?.detail || 'Erro ao realizar operação.';
    this.snackBar.open(msg, 'Fechar', { duration: 4500 });
  }

  getMovementLabel(type: string): string {
    const map: Record<string, string> = {
      INITIAL_STOCK: 'Cadastro Inicial em Estoque',
      RESERVATION: 'Reserva de Equipamento',
      RESERVATION_CANCEL: 'Cancelamento de Reserva',
      ASSIGNMENT: 'Entrega / Atribuição',
      RETURN: 'Devolução Física',
      INSPECTION_RELEASE: 'Liberação pós-inspeção',
      MAINTENANCE: 'Envio para Manutenção',
      TRANSFER: 'Transferência de Unidade',
      DECOMMISSION: 'Baixa Definitiva'
    };
    return map[type] || type;
  }
}
