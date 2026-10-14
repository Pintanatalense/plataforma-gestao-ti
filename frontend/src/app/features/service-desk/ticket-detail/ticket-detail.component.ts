import { Component, OnInit, inject, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterModule } from '@angular/router';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
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
  TicketInteraction
} from '../ticket.service';
import { AuthService } from '../../../core/auth/auth.service';
import { StockItem, StockService } from '../../../core/services/stock.service';
import { AttachmentsComponent } from '../../../shared/components/attachments/attachments.component';

@Component({
  selector: 'app-ticket-detail',
  standalone: true,
  imports: [
    CommonModule,
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
  public authService = inject(AuthService);
  private fb = inject(FormBuilder);
  private snackBar = inject(MatSnackBar);
  private cdr = inject(ChangeDetectorRef);

  ticket: Ticket | null = null;
  history: TicketHistoryItem[] = [];
  isLoadingHistory = false;

  messageForm: FormGroup;
  materialForm: FormGroup;
  statusNoteForm: FormGroup;

  isTechnician = false;
  showStatusModal = false;
  pendingStatus: string | null = null;

  stockItems: StockItem[] = [];
  materialColumns = ['item', 'quantity', 'created_at'];
  categories: TicketCategory[] = [];

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
    }
  }

  loadTicket(id: string) {
    this.ticketService.getTicket(id).subscribe({
      next: (data) => {
        this.ticket = data;
        this.loadHistory(id);
        this.cdr.markForCheck();
        this.scrollToBottom();
      },
      error: (err) => {
        console.error(err);
        this.snackBar.open('Erro ao carregar chamado.', 'Fechar', { duration: 3000 });
      }
    });
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

  getHistoryIcon(eventType: string): string {
    switch (eventType) {
      case 'ticket.created': return 'add_task';
      case 'ticket.status_changed': return 'swap_horiz';
      case 'ticket.closed': return 'task_alt';
      case 'ticket.interaction_added': return 'forum';
      case 'ticket.material_added': return 'inventory_2';
      case 'ticket.assigned': return 'person_pin';
      case 'ticket.priority_changed': return 'flag';
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
      default: return 'type-default';
    }
  }

  private scrollToBottom() {
    setTimeout(() => {
      const container = document.getElementById('chat-container');
      if (container) {
        container.scrollTop = container.scrollHeight;
      }
    }, 100);
  }
}
