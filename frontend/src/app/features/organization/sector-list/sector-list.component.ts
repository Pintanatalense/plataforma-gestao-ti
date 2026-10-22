import { Component, OnInit, inject, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatTableModule } from '@angular/material/table';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { apiErrorMessage } from '../../../core/http/api-error';
import { LoadStateComponent } from '../../../shared/components/load-state/load-state.component';
import { OrganizationService, Sector } from '../../../core/services/organization.service';
import { SectorDialogComponent } from './sector-dialog.component';

@Component({
  selector: 'app-sector-list',
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
  templateUrl: './sector-list.component.html',
  styleUrls: ['./sector-list.component.scss']
})
export class SectorList implements OnInit {
  private orgService = inject(OrganizationService);
  private dialog = inject(MatDialog);
  private snackBar = inject(MatSnackBar);
  private cdr = inject(ChangeDetectorRef);

  displayedColumns: string[] = ['unit', 'code', 'name', 'status', 'actions'];
  dataSource: Sector[] = [];

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
    this.orgService.getSectors().subscribe({
      next: (data) => {
        this.dataSource = data;
        this.loaded = true;
        this.isLoading = false;
        this.loadError = null;
        this.cdr.markForCheck();
      },
      error: (err) => {
        const msg = apiErrorMessage(err, 'Erro ao carregar setores.');
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

  openDialog(sector?: Sector) {
    const dialogRef = this.dialog.open(SectorDialogComponent, {
      width: '400px',
      data: sector || null
    });

    dialogRef.afterClosed().subscribe(result => {
      if (result) {
        if (sector) {
          this.orgService.updateSector(sector.id, result).subscribe({
            next: () => {
              this.snackBar.open('Setor atualizado com sucesso', 'Fechar', { duration: 3000 });
              this.loadData();
            },
            error: (err) => {
              this.snackBar.open(apiErrorMessage(err, 'Erro ao atualizar setor'), 'Fechar', { duration: 4000 });
            }
          });
        } else {
          this.orgService.createSector(result).subscribe({
            next: () => {
              this.snackBar.open('Setor criado com sucesso', 'Fechar', { duration: 3000 });
              this.loadData();
            },
            error: (err) => {
              this.snackBar.open(apiErrorMessage(err, 'Erro ao criar setor'), 'Fechar', { duration: 4000 });
            }
          });
        }
      }
    });
  }

  deleteSector(id: string) {
    if (confirm('Tem certeza que deseja inativar/remover este setor?')) {
      this.orgService.deleteSector(id).subscribe({
        next: () => {
          this.snackBar.open('Setor inativado com sucesso', 'Fechar', { duration: 3000 });
          this.loadData();
        },
        error: (err) => {
          this.snackBar.open(apiErrorMessage(err, 'Erro ao inativar setor'), 'Fechar', { duration: 4000 });
        }
      });
    }
  }
}
