import { Component, OnInit, inject } from '@angular/core';
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

import { Ticket, TicketMaterial, TicketService } from '../ticket.service';
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

  ticket: Ticket | null = null;
  messageForm: FormGroup;
  materialForm: FormGroup;
  isTechnician = false;

  stockItems: StockItem[] = [];
  materialColumns = ['item', 'quantity', 'created_at'];

  constructor() {
    this.messageForm = this.fb.group({
      message: ['', Validators.required],
      is_internal: [false]
    });

    this.materialForm = this.fb.group({
      stock_item_id: ['', Validators.required],
      quantity: [1, [Validators.required, Validators.min(1)]]
    });
  }

  ngOnInit() {
    this.isTechnician =
      this.authService.hasPermission('service_desk.tickets.read_internal') ||
      !!this.authService.currentUserValue?.is_admin;

    this.route.paramMap.subscribe((params) => {
      const id = params.get('id');
      if (id) {
        this.loadTicket(id);
      }
    });

    if (this.isTechnician) {
      this.loadStockItems();
    }
  }

  loadTicket(id: string) {
    this.ticketService.getTicket(id).subscribe({
      next: (data) => (this.ticket = data),
      error: (err) => console.error(err)
    });
  }

  loadStockItems() {
    this.stockService.getItems().subscribe({
      next: (items) => (this.stockItems = items),
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
      },
      error: (err) => console.error(err)
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
      },
      error: (err) => {
        console.error(err);
        const msg = err?.error?.detail || 'Erro ao lançar material.';
        this.snackBar.open(msg, 'Fechar', { duration: 5000 });
      }
    });
  }

  closeTicket() {
    if (!this.ticket) return;
    this.ticketService.updateTicket(this.ticket.id, { status: 'CLOSED' }).subscribe({
      next: (updatedTicket) => (this.ticket = updatedTicket),
      error: (err) => console.error(err)
    });
  }

  isMyMessage(authorId: string): boolean {
    return this.authService.currentUserValue?.id === authorId;
  }

  getStockItemName(stockItemId: string): string {
    const item = this.stockItems.find((s) => s.id === stockItemId);
    return item ? item.name : `Insumo #${stockItemId.slice(0, 8)}`;
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
