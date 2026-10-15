import { Component, OnInit, inject, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterModule } from '@angular/router';
import { FormsModule, FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatCardModule } from '@angular/material/card';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatChipsModule } from '@angular/material/chips';
import { MatDividerModule } from '@angular/material/divider';
import { MatTabsModule } from '@angular/material/tabs';
import { MatSelectModule } from '@angular/material/select';
import { MatTableModule } from '@angular/material/table';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatMenuModule } from '@angular/material/menu';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';

import {
  Ticket,
  TicketMaterial,
  TicketService,
  TicketCategory,
  CategoryFormField,
  TicketHistoryItem,
  TicketInteraction,
  TicketAssetBrief
} from '../ticket.service';
import { AuthService } from '../../../core/auth/auth.service';
import { StockItem, StockService } from '../../../core/services/stock.service';
import { Employee, OrganizationService } from '../../../core/services/organization.service';
import { AdminService, WhatsAppTemplate } from '../../../core/services/admin.service';
import { AttachmentsComponent } from '../../../shared/components/attachments/attachments.component';
import { AttachmentsService, Attachment } from '../../../core/services/attachments.service';
import { Asset, AssetService } from '../../../core/services/asset.service';
import { HttpResponse } from '@angular/common/http';

@Component({
  selector: 'app-ticket-detail',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    ReactiveFormsModule,
    RouterModule,
    MatButtonModule,
    MatIconModule,
    MatInputModule,
    MatCardModule,
    MatCheckboxModule,
    MatChipsModule,
    MatDividerModule,
    MatTabsModule,
    MatSelectModule,
    MatTableModule,
    MatSnackBarModule,
    MatMenuModule,
    MatTooltipModule,
    MatProgressSpinnerModule,
    AttachmentsComponent
  ],
  templateUrl: './ticket-detail.component.html',
  styleUrls: ['./ticket-detail.component.scss']
})
export class TicketDetailComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private ticketService = inject(TicketService);
  private stockService = inject(StockService);
  private orgService = inject(OrganizationService);
  private adminService = inject(AdminService);
  public attachmentsService = inject(AttachmentsService);
  public authService = inject(AuthService);
  public assetService = inject(AssetService);
  private fb = inject(FormBuilder);
  private snackBar = inject(MatSnackBar);
  private cdr = inject(ChangeDetectorRef);

  showLinkAssetModal = false;
  allAssets: Asset[] = [];
  assetSearchTerm = '';
  selectedAssetToLink: Asset | null = null;
  linkingAsset = false;


  ticket: Ticket | null = null;
  history: TicketHistoryItem[] = [];
  attachments: Attachment[] = [];
  isLoadingHistory = false;
  isUploadingChatFile = false;

  messageForm: FormGroup;
  materialForm: FormGroup;
  statusNoteForm: FormGroup;
  assetActionForm: FormGroup;

  isTechnician = false;
  showStatusModal = false;
  pendingStatus: string | null = null;

  stockItems: StockItem[] = [];
  materialColumns = ['item', 'quantity', 'created_at'];
  categories: TicketCategory[] = [];
  employees: Employee[] = [];

  selectedAssetForAction: TicketAssetBrief | null = null;
  assetActionType: 'reserve' | 'deliver' | 'return' | 'inspect' | null = null;

  // WhatsApp Quick Send & Anti-Ban
  waTemplates: WhatsAppTemplate[] = [];
  selectedWaTemplateId: string = '';
  waCustomMessage: string = '';
  waObservacao: string = '';
  showWhatsAppModal: boolean = false;
  sendingWhatsApp: boolean = false;
  loadingWaPreview: boolean = false;

  constructor() {
    this.messageForm = this.fb.group({
      message: ['', Validators.required],
      is_internal: [false]
    });

    this.materialForm = this.fb.group({
      stock_item_id: ['', Validators.required],
      quantity: [1, [Validators.required, Validators.min(1)]]
    });

    this.statusNoteForm = this.fb.group({
      notes: ['']
    });

    this.assetActionForm = this.fb.group({
      employee_id: [''],
      approved: [true],
      notes: ['']
    });
  }

  ngOnInit() {
    this.isTechnician =
      this.authService.hasPermission('service_desk.tickets.manage') ||
      !!this.authService.currentUserValue?.is_admin;

    this.route.paramMap.subscribe((params) => {
      const id = params.get('id');
      if (id) {
        this.loadTicket(id);
      }
    });

    this.ticketService.getCategories().subscribe({
      next: (cats) => {
        this.categories = cats;
        this.cdr.markForCheck();
      },
      error: () => {}
    });

    if (this.isTechnician) {
      this.loadStockItems();
      this.loadEmployees();
    }
  }

  loadTicket(id: string) {
    this.ticketService.getTicket(id).subscribe({
      next: (data) => {
        this.ticket = data;
        this.loadHistory(id);
        this.loadAttachments(id);
        this.cdr.markForCheck();
        this.scrollToBottom();
      },
      error: (err) => {
        console.error(err);
        this.snackBar.open('Erro ao carregar chamado.', 'Fechar', { duration: 3000 });
      }
    });
  }

  loadAttachments(ticketId: string): void {
    this.attachmentsService.getAttachments('TICKET', ticketId).subscribe({
      next: (atts) => {
        this.attachments = atts || [];
        this.cdr.markForCheck();
      },
      error: () => {}
    });
  }

  onTicketAttachmentsChanged(atts: Attachment[]): void {
    this.attachments = atts || [];
    this.cdr.markForCheck();
  }

  onChatFileSelected(event: any): void {
    const file: File = event.target.files?.[0];
    if (!file || !this.ticket) return;

    this.isUploadingChatFile = true;
    this.cdr.markForCheck();

    this.attachmentsService.uploadFile(file, 'TICKET', this.ticket.id).subscribe({
      next: (res: any) => {
        if (res instanceof HttpResponse) {
          this.isUploadingChatFile = false;
          this.snackBar.open(`Arquivo "${file.name}" anexado com sucesso ao chamado!`, 'OK', { duration: 3500 });
          this.loadAttachments(this.ticket!.id);
          this.cdr.detectChanges();
        }
      },
      error: (err) => {
        this.isUploadingChatFile = false;
        this.snackBar.open(err?.error?.detail || 'Erro ao anexar arquivo ao chamado', 'Fechar', { duration: 4000 });
        this.cdr.detectChanges();
      }
    });

    event.target.value = null;
  }

  downloadAttachment(att: Attachment): void {
    this.attachmentsService.downloadAttachment(att.id, att.filename);
  }

  loadHistory(id: string) {
    this.isLoadingHistory = true;
    this.ticketService.getTicketHistory(id).subscribe({
      next: (h) => {
        this.history = h;
        this.isLoadingHistory = false;
        this.cdr.markForCheck();
      },
      error: (err) => {
        console.error('Erro ao carregar histórico:', err);
        this.isLoadingHistory = false;
        this.cdr.markForCheck();
      }
    });
  }

  isRequester(): boolean {
    if (!this.ticket || !this.authService.currentUserValue) return false;
    return this.ticket.requester_id === this.authService.currentUserValue.employee_id;
  }

  canCloseTicket(): boolean {
    if (!this.ticket) return false;
    return this.ticket.status !== 'CLOSED' && (this.isTechnician || this.isRequester());
  }

  hasCustomFields(): boolean {
    return !!this.ticket?.custom_fields && Object.keys(this.ticket.custom_fields).length > 0;
  }

  getCustomFieldEntries(): { key: string; label: string; value: any; type?: string }[] {
    if (!this.ticket?.custom_fields) return [];
    const fields = this.ticket.custom_fields;
    const cat = this.categories.find((c) => c.id === this.ticket?.category_id);
    const schema = cat?.form_schema || [];

    return Object.entries(fields).map(([key, val]) => {
      const match = schema.find((s: CategoryFormField) => s.id === key);
      return {
        key,
        label: match?.label || key.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase()),
        value: val,
        type: match?.type
      };
    });
  }

  getCategoryName(): string {
    if (this.ticket?.category?.name) return this.ticket.category.name;
    if (!this.ticket?.category_id) return 'Não categorizado';
    const cat = this.categories.find((c) => c.id === this.ticket?.category_id);
    return cat ? cat.name : 'Categoria Geral';
  }

  loadStockItems() {
    this.stockService.getItems().subscribe({
      next: (items) => {
        this.stockItems = items;
        this.cdr.markForCheck();
      },
      error: () => {}
    });
  }

  sendMessage() {
    if (this.messageForm.invalid || !this.ticket) return;

    const { message, is_internal } = this.messageForm.value;

    this.ticketService.addInteraction(this.ticket.id, message, is_internal).subscribe({
      next: (interaction) => {
        this.ticket?.interactions.push(interaction);
        this.messageForm.reset({ is_internal: false });
        this.scrollToBottom();
        this.loadHistory(this.ticket!.id);
        this.cdr.markForCheck();
      },
      error: (err) => {
        console.error(err);
        const msg = err?.error?.detail || 'Erro ao enviar mensagem.';
        this.snackBar.open(msg, 'Fechar', { duration: 4000 });
      }
    });
  }

  addMaterial() {
    if (this.materialForm.invalid || !this.ticket) return;

    const val = this.materialForm.value;
    const payload = {
      stock_item_id: val.stock_item_id,
      quantity: Number(val.quantity || 1)
    };

    this.ticketService.addMaterial(this.ticket.id, payload).subscribe({
      next: (mat) => {
        this.snackBar.open('Material lançado com sucesso!', 'Fechar', { duration: 3000 });
        if (!this.ticket!.materials) this.ticket!.materials = [];
        this.ticket!.materials.push(mat);
        this.materialForm.reset({ quantity: 1 });
        this.loadHistory(this.ticket!.id);
        this.cdr.markForCheck();
      },
      error: (err) => {
        console.error(err);
        const msg = err?.error?.detail || 'Erro ao lançar material.';
        this.snackBar.open(msg, 'Fechar', { duration: 5000 });
      }
    });
  }

  openStatusChange(newStatus: string) {
    this.pendingStatus = newStatus;
    this.statusNoteForm.reset();
    this.showStatusModal = true;
  }

  cancelStatusChange() {
    this.showStatusModal = false;
    this.pendingStatus = null;
    this.statusNoteForm.reset();
  }

  confirmStatusChange() {
    if (!this.ticket || !this.pendingStatus) return;

    const notes = this.statusNoteForm.value.notes?.trim() || undefined;

    this.ticketService.updateTicketStatus(this.ticket.id, this.pendingStatus, notes).subscribe({
      next: (updatedTicket) => {
        this.ticket = updatedTicket;
        const statusLabel = this.getStatusLabel(this.ticket.status);
        this.snackBar.open(`Status alterado para "${statusLabel}" com sucesso!`, 'Fechar', { duration: 3500 });
        this.cancelStatusChange();
        this.loadHistory(this.ticket.id);
        this.cdr.markForCheck();
      },
      error: (err) => {
        console.error(err);
        const msg = err?.error?.detail || 'Erro ao alterar status do chamado.';
        this.snackBar.open(msg, 'Fechar', { duration: 5000 });
      }
    });
  }

  isMyMessage(authorId: string): boolean {
    const user = this.authService.currentUserValue;
    if (!user) return false;
    return user.id === authorId || (!!user.employee_id && user.employee_id === authorId);
  }

  getAuthorDisplayName(msg: TicketInteraction): string {
    if (this.isMyMessage(msg.author_id)) return 'Você';
    return msg.author_name || msg.author_email || 'Usuário';
  }

  getStockItemName(stockItemId: string): string {
    const item = this.stockItems.find((s) => s.id === stockItemId);
    return item ? item.name : `Insumo #${stockItemId.slice(0, 8)}`;
  }

  getStatusLabel(status: string): string {
    switch (status) {
      case 'OPENED': return 'Aberto';
      case 'IN_PROGRESS': return 'Em Atendimento';
      case 'PENDING': return 'Pendente';
      case 'RESOLVED': return 'Resolvido';
      case 'CLOSED': return 'Encerrado';
      default: return status;
    }
  }

  loadEmployees() {
    this.orgService.getEmployees().subscribe({
      next: (emps) => {
        this.employees = emps;
        this.cdr.markForCheck();
      },
      error: () => {}
    });
  }

  getEmployeeName(empId?: string | null): string {
    if (!empId) return '-';
    const emp = this.employees.find((e) => e.id === empId);
    return emp ? `${emp.name} (${emp.registration})` : `Colaborador #${empId.substring(0, 8)}`;
  }

  openAssetActionModal(asset: TicketAssetBrief, action: 'reserve' | 'deliver' | 'return' | 'inspect') {
    this.selectedAssetForAction = asset;
    this.assetActionType = action;
    const defaultEmpId = asset.employee_id || this.ticket?.requester_id || '';
    this.assetActionForm.reset({
      employee_id: defaultEmpId,
      approved: true,
      notes: ''
    });
  }

  closeAssetActionModal() {
    this.selectedAssetForAction = null;
    this.assetActionType = null;
    this.assetActionForm.reset();
  }

  submitAssetAction() {
    if (!this.ticket || !this.selectedAssetForAction || !this.assetActionType) return;

    const val = this.assetActionForm.value;
    const ticketId = this.ticket.id;
    const assetId = this.selectedAssetForAction.id;

    let obs;
    let successMsg = '';

    if (this.assetActionType === 'reserve') {
      if (!val.employee_id) {
        this.snackBar.open('Selecione o colaborador para a reserva.', 'Fechar', { duration: 3000 });
        return;
      }
      obs = this.ticketService.reserveTicketAsset(ticketId, assetId, {
        employee_id: val.employee_id,
        notes: val.notes || undefined
      });
      successMsg = `Ativo #${this.selectedAssetForAction.tag} reservado com sucesso!`;
    } else if (this.assetActionType === 'deliver') {
      if (!val.employee_id) {
        this.snackBar.open('Selecione o colaborador destinatário.', 'Fechar', { duration: 3000 });
        return;
      }
      obs = this.ticketService.deliverTicketAsset(ticketId, assetId, {
        employee_id: val.employee_id,
        notes: val.notes || undefined
      });
      successMsg = `Ativo #${this.selectedAssetForAction.tag} entregue com sucesso!`;
    } else if (this.assetActionType === 'return') {
      obs = this.ticketService.returnTicketAsset(ticketId, assetId, {
        notes: val.notes || undefined
      });
      successMsg = `Devolução física registrada! Ativo #${this.selectedAssetForAction.tag} encaminhado para inspeção técnica.`;
    } else if (this.assetActionType === 'inspect') {
      obs = this.ticketService.inspectTicketAsset(ticketId, assetId, {
        approved: !!val.approved,
        notes: val.notes || undefined
      });
      successMsg = val.approved
        ? `Ativo #${this.selectedAssetForAction.tag} aprovado na conferência e liberado para o estoque!`
        : `Ativo #${this.selectedAssetForAction.tag} reprovado e encaminhado para manutenção!`;
    }

    if (obs) {
      obs.subscribe({
        next: () => {
          this.snackBar.open(successMsg, 'Fechar', { duration: 4000 });
          this.closeAssetActionModal();
          this.loadTicket(ticketId);
        },
        error: (err) => {
          console.error(err);
          const msg = err?.error?.error?.message || err?.error?.detail || 'Erro ao processar operação do ativo.';
          this.snackBar.open(msg, 'Fechar', { duration: 5000 });
        }
      });
    }
  }

  getAssetStatusLabel(status: string): string {
    switch (status) {
      case 'IN_STOCK': return 'Em Estoque';
      case 'RESERVED': return 'Reservado';
      case 'IN_USE': return 'Em Uso';
      case 'PENDING_INSPECTION': return 'Aguardando Inspeção';
      case 'MAINTENANCE': return 'Em Manutenção';
      case 'DECOMMISSIONED': return 'Baixado';
      default: return status;
    }
  }

  getAssetStatusBadgeClass(status: string): string {
    switch (status) {
      case 'IN_STOCK': return 'badge-stock';
      case 'RESERVED': return 'badge-reserved';
      case 'IN_USE': return 'badge-use';
      case 'PENDING_INSPECTION': return 'badge-inspection';
      case 'MAINTENANCE': return 'badge-maint';
      case 'DECOMMISSIONED': return 'badge-decom';
      default: return 'badge-default';
    }
  }

  getHistoryIcon(eventType: string): string {
    switch (eventType) {
      case 'ticket.created': return 'add_task';
      case 'ticket.status_changed': return 'swap_horiz';
      case 'ticket.closed': return 'task_alt';
      case 'ticket.interaction_added': return 'forum';
      case 'ticket.material_added': return 'inventory_2';
      case 'ticket.assigned': return 'person_pin';
      case 'ticket.priority_changed': return 'flag';
      case 'ticket.asset_linked': return 'add_link';
      case 'ticket.asset_unlinked': return 'link_off';
      case 'ticket.asset_reserved': return 'bookmark';
      case 'ticket.asset_delivered': return 'handshake';
      case 'ticket.asset_returned': return 'keyboard_return';
      case 'ticket.asset_inspected': return 'verified';
      default: return 'history';
    }
  }

  getHistoryColorClass(eventType: string): string {
    switch (eventType) {
      case 'ticket.created': return 'type-create';
      case 'ticket.closed': return 'type-close';
      case 'ticket.status_changed': return 'type-status';
      case 'ticket.interaction_added': return 'type-chat';
      case 'ticket.material_added': return 'type-mat';
      case 'ticket.assigned': return 'type-assign';
      case 'ticket.asset_linked': return 'type-create';
      case 'ticket.asset_unlinked': return 'type-close';
      case 'ticket.asset_reserved': return 'type-assign';
      case 'ticket.asset_delivered': return 'type-create';
      case 'ticket.asset_returned': return 'type-status';
      case 'ticket.asset_inspected': return 'type-close';
      default: return 'type-default';
    }
  }

  // --- WhatsApp Quick Send & Anti-Ban Methods ---
  openWhatsAppModal() {
    this.showWhatsAppModal = true;
    this.waObservacao = '';
    this.waCustomMessage = '';
    this.selectedWaTemplateId = '';
    if (this.waTemplates.length === 0) {
      this.loadWaTemplates();
    } else {
      this.suggestTemplateForStatus();
    }
  }

  closeWhatsAppModal() {
    this.showWhatsAppModal = false;
    this.selectedWaTemplateId = '';
    this.waCustomMessage = '';
    this.waObservacao = '';
    this.sendingWhatsApp = false;
    this.loadingWaPreview = false;
  }

  loadWaTemplates() {
    this.adminService.getWhatsAppTemplates(undefined, true).subscribe({
      next: (tpls) => {
        this.waTemplates = tpls;
        if (this.ticket && tpls.length > 0) {
          this.suggestTemplateForStatus();
        }
        this.cdr.markForCheck();
      },
      error: (err) => {
        console.error('Erro ao carregar templates WhatsApp:', err);
      }
    });
  }

  suggestTemplateForStatus() {
    if (!this.ticket || this.waTemplates.length === 0) return;
    let matchCode = '';
    if (this.ticket.status === 'OPENED') matchCode = 'TICKET_OPENED';
    else if (this.ticket.status === 'IN_PROGRESS') matchCode = 'TICKET_IN_PROGRESS';
    else if (this.ticket.status === 'PENDING') matchCode = 'AWAITING_USER';
    else if (this.ticket.status === 'RESOLVED') matchCode = 'TICKET_RESOLVED';

    const found = this.waTemplates.find(t => t.code === matchCode);
    if (found) {
      this.selectedWaTemplateId = found.id;
      this.onWaTemplateChange();
    }
  }

  onWaTemplateChange() {
    if (!this.selectedWaTemplateId) {
      return;
    }
    const tpl = this.waTemplates.find(t => t.id === this.selectedWaTemplateId);
    if (!tpl || !this.ticket) return;

    this.loadingWaPreview = true;
    this.adminService.previewWhatsAppTemplate(tpl.id, {
      ticket_id: this.ticket.id,
      observacao: this.waObservacao || undefined
    }).subscribe({
      next: (res) => {
        this.waCustomMessage = res.rendered_message;
        this.loadingWaPreview = false;
        this.cdr.markForCheck();
      },
      error: () => {
        this.waCustomMessage = tpl.content
          .replace(/\{\{solicitante\}\}/g, this.ticket?.requester_name || 'Solicitante')
          .replace(/\{\{protocolo\}\}/g, this.ticket?.id ? this.ticket.id.slice(0, 8) : '')
          .replace(/\{\{titulo\}\}/g, this.ticket?.title || '')
          .replace(/\{\{status\}\}/g, this.getStatusLabel(this.ticket?.status || ''))
          .replace(/\{\{observacao\}\}/g, this.waObservacao || '');
        this.loadingWaPreview = false;
        this.cdr.markForCheck();
      }
    });
  }

  onWaObservacaoChange() {
    if (this.selectedWaTemplateId) {
      this.onWaTemplateChange();
    }
  }

  sendWhatsAppToRequester() {
    if (!this.ticket) return;
    if (!this.ticket.requester_phone) {
      this.snackBar.open('Este solicitante não possui telefone cadastrado.', 'Fechar', { duration: 4000 });
      return;
    }
    if (!this.waCustomMessage.trim()) {
      this.snackBar.open('Por favor, informe a mensagem a ser enviada.', 'Fechar', { duration: 3000 });
      return;
    }

    this.sendingWhatsApp = true;
    this.adminService.sendTicketWhatsApp(this.ticket.id, {
      template_id: this.selectedWaTemplateId || undefined,
      custom_message: this.waCustomMessage.trim(),
      observacao: this.waObservacao.trim() || undefined
    }).subscribe({
      next: () => {
        this.snackBar.open('✅ Mensagem enviada para a fila segura do WhatsApp com sucesso!', 'Fechar', { duration: 4000 });
        this.closeWhatsAppModal();
        this.loadTicket(this.ticket!.id);
      },
      error: (err) => {
        console.error('Erro ao enviar WhatsApp:', err);
        const msg = err?.error?.detail || 'Erro ao enfileirar mensagem de WhatsApp.';
        this.snackBar.open(msg, 'Fechar', { duration: 5000 });
        this.sendingWhatsApp = false;
        this.cdr.markForCheck();
      }
    });
  }

  private scrollToBottom() {
    setTimeout(() => {
      const container = document.getElementById('chat-container');
      if (container) {
        container.scrollTop = container.scrollHeight;
      }
    }, 100);
  }

  // ============================================================================
  // Vincular / Desvincular Ativos
  // ============================================================================
  openLinkAssetModal() {
    this.assetSearchTerm = '';
    this.selectedAssetToLink = null;
    this.showLinkAssetModal = true;
    this.assetService.getAssets().subscribe({
      next: (assets) => {
        const currentIds = (this.ticket?.assets || []).map((a) => a.id);
        this.allAssets = assets.filter((a) => !currentIds.includes(a.id));
      },
      error: (err) => {
        console.error('Erro ao carregar ativos para vínculo:', err);
      }
    });
  }

  closeLinkAssetModal() {
    this.showLinkAssetModal = false;
    this.selectedAssetToLink = null;
    this.assetSearchTerm = '';
  }

  get filteredAssetsToLink(): Asset[] {
    if (!this.assetSearchTerm.trim()) {
      return this.allAssets;
    }
    const q = this.assetSearchTerm.toLowerCase();
    return this.allAssets.filter(
      (a) =>
        a.tag.toLowerCase().includes(q) ||
        a.name.toLowerCase().includes(q) ||
        (a.category?.name && a.category.name.toLowerCase().includes(q))
    );
  }

  selectAssetToLink(asset: Asset) {
    this.selectedAssetToLink = asset;
  }

  confirmLinkAsset() {
    if (!this.ticket || !this.selectedAssetToLink) return;
    this.linkingAsset = true;
    const ticketId = this.ticket.id;
    const assetId = this.selectedAssetToLink.id;

    this.ticketService.linkAssetToTicket(ticketId, assetId).subscribe({
      next: () => {
        this.snackBar.open(
          `Equipamento #${this.selectedAssetToLink?.tag} vinculado com sucesso!`,
          'Fechar',
          { duration: 3000 }
        );
        this.linkingAsset = false;
        this.closeLinkAssetModal();
        this.loadTicket(ticketId);
      },
      error: (err) => {
        this.linkingAsset = false;
        console.error(err);
        const msg =
          err?.error?.error?.message ||
          err?.error?.detail ||
          'Erro ao vincular equipamento.';
        this.snackBar.open(msg, 'Fechar', { duration: 4000 });
      }
    });
  }

  unlinkAsset(asset: TicketAssetBrief) {
    if (!this.ticket) return;
    if (
      !confirm(
        `Deseja desvincular o equipamento #${asset.tag} (${asset.name}) deste chamado?`
      )
    ) {
      return;
    }

    const ticketId = this.ticket.id;
    this.ticketService.unlinkAssetFromTicket(ticketId, asset.id).subscribe({
      next: () => {
        this.snackBar.open(
          `Equipamento #${asset.tag} desvinculado do chamado.`,
          'Fechar',
          { duration: 3000 }
        );
        this.loadTicket(ticketId);
      },
      error: (err) => {
        console.error(err);
        const msg =
          err?.error?.error?.message ||
          err?.error?.detail ||
          'Erro ao desvincular equipamento.';
        this.snackBar.open(msg, 'Fechar', { duration: 4000 });
      }
    });
  }
}
