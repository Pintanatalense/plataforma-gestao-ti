import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterModule } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';

import { TicketService, TicketCategory } from '../ticket.service';
import { Asset, AssetService } from '../../../core/services/asset.service';

@Component({
  selector: 'app-ticket-create',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    RouterModule,
    MatButtonModule,
    MatInputModule,
    MatSelectModule,
    MatIconModule,
    MatSnackBarModule
  ],
  templateUrl: './ticket-create.component.html',
  styleUrls: ['./ticket-create.component.scss']
})
export class TicketCreateComponent implements OnInit {
  private fb = inject(FormBuilder);
  private ticketService = inject(TicketService);
  private assetService = inject(AssetService);
  private router = inject(Router);
  private snackBar = inject(MatSnackBar);

  ticketForm: FormGroup;
  categories: TicketCategory[] = [];
  availableAssets: Asset[] = [];

  constructor() {
    this.ticketForm = this.fb.group({
      title: ['', Validators.required],
      description: ['', Validators.required],
      priority: ['LOW', Validators.required],
      category_id: [null],
      asset_id: [null]
    });
  }

  ngOnInit() {
    this.ticketService.getCategories().subscribe({
      next: (data) => (this.categories = data),
      error: (err) => console.error(err)
    });

    this.assetService.getAssets().subscribe({
      next: (assets) => (this.availableAssets = assets),
      error: () => {}
    });
  }

  onSubmit() {
    if (this.ticketForm.valid) {
      const val = this.ticketForm.value;
      const payload: any = {
        title: val.title,
        description: val.description,
        priority: val.priority,
        category_id: val.category_id || undefined,
        asset_ids: val.asset_id ? [val.asset_id] : []
      };

      this.ticketService.createTicket(payload).subscribe({
        next: (ticket) => {
          this.snackBar.open('Chamado aberto com sucesso!', 'Fechar', { duration: 3000 });
          this.router.navigate(['/service-desk', ticket.id]);
        },
        error: (err) => {
          console.error(err);
          const msg = err?.error?.detail || 'Erro ao abrir chamado.';
          this.snackBar.open(msg, 'Fechar', { duration: 5000 });
        }
      });
    }
  }
}
