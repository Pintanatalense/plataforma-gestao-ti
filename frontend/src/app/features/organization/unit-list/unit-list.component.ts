import { Component, OnInit, inject, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatTableModule } from '@angular/material/table';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { apiErrorMessage } from '../../../core/http/api-error';
import { LoadStateComponent } from '../../../shared/components/load-state/load-state.component';
import { OrganizationService, Unit } from '../../../core/services/organization.service';
import { UnitDialogComponent } from './unit-dialog.component';

@Component({
  selector: 'app-unit-list',
  standalone: true,
  imports: [
    CommonModule,
    MatTableModule,
    MatButtonModule,
    MatIconModule,
    MatDialogModule,
    MatSnackBarModule,
    LoadStateComponent
  ],
  templateUrl: './unit-list.component.html',
  styleUrls: ['./unit-list.component.scss']
})
export class UnitList implements OnInit {
  private orgService = inject(OrganizationService);
  private dialog = inject(MatDialog);
  private snackBar = inject(MatSnackBar);
  private cdr = inject(ChangeDetectorRef);

  displayedColumns: string[] = ['code', 'name', 'status', 'actions'];
  dataSource: Unit[] = [];

  /** Primeira carga em andamento / falha (uma recarga que falha mantém a tabela e só avisa). */
  isLoading = true;
  loadError: string | null = null;
  private loaded = false;

  ngOnInit(): void {
    this.loadData();
  }

  loadData() {
    if (!this.loaded) {
      this.isLoading = true;
      this.loadError = null;
    }
    this.orgService.getUnits().subscribe({
      next: (data) => {
        this.dataSource = data;
        this.loaded = true;
        this.isLoading = false;
        this.loadError = null;
        this.cdr.markForCheck();
      },
      error: (err) => {
        const msg = apiErrorMessage(err, 'Erro ao carregar unidades.');
        if (this.loaded) {
          this.snackBar.open(msg, 'Fechar', { duration: 4000 });
        } else {
          this.isLoading = false;
          this.loadError = msg;
        }
        this.cdr.markForCheck();
      }
    });
  }

  openDialog(unit?: Unit) {
    const dialogRef = this.dialog.open(UnitDialogComponent, {
      width: '400px',
      data: unit || null
    });

    dialogRef.afterClosed().subscribe(result => {
      if (result) {
        if (unit) {
          this.orgService.updateUnit(unit.id, result).subscribe({
            next: () => {
              this.snackBar.open('Unidade atualizada com sucesso', 'Fechar', { duration: 3000 });
              this.loadData();
            },
            error: (err) => {
              this.snackBar.open(apiErrorMessage(err, 'Erro ao atualizar unidade'), 'Fechar', { duration: 4000 });
            }
          });
        } else {
          this.orgService.createUnit(result).subscribe({
            next: () => {
              this.snackBar.open('Unidade criada com sucesso', 'Fechar', { duration: 3000 });
              this.loadData();
            },
            error: (err) => {
              this.snackBar.open(apiErrorMessage(err, 'Erro ao criar unidade'), 'Fechar', { duration: 4000 });
            }
          });
        }
      }
    });
  }

  deleteUnit(id: string) {
    if (confirm('Tem certeza que deseja inativar/remover esta unidade?')) {
      this.orgService.deleteUnit(id).subscribe({
        next: () => {
          this.snackBar.open('Unidade inativada com sucesso', 'Fechar', { duration: 3000 });
          this.loadData();
        },
        error: (err) => {
          this.snackBar.open(apiErrorMessage(err, 'Erro ao inativar unidade'), 'Fechar', { duration: 4000 });
        }
      });
    }
  }
}
