import os
import warnings

from sympy import Symbol, Eq, Abs

import modulus.sym
from modulus.sym.hydra import to_absolute_path, instantiate_arch, ModulusConfig
from modulus.sym.solver import Solver
from modulus.sym.domain import Domain
from modulus.sym.geometry.primitives_2d import Rectangle
from modulus.sym.domain.constraint import (
    PointwiseBoundaryConstraint,
    PointwiseInteriorConstraint,
)
from modulus.sym.domain.validator import PointwiseValidator
from modulus.sym.domain.inferencer import PointwiseInferencer
from modulus.sym.key import Key
from modulus.sym.eq.pdes.navier_stokes import NavierStokes
from modulus.sym.utils.io import (
    csv_to_dict,
    ValidatorPlotter,
    InferencerPlotter,
)


@modulus.sym.main(config_path="/content/drive/MyDrive/Thesis/Lid_Driven_Cavity", config_name="ldc_config.yaml")
def run(cfg: ModulusConfig) -> None:
    # make list of nodes to unroll graph on
    ns = NavierStokes(nu=0.01, rho=1.0, dim=2, time=False)
    flow_net = instantiate_arch(
        input_keys=[Key("x"), Key("y")],
        output_keys=[Key("u"), Key("v"), Key("p")],
        cfg=cfg.arch.fully_connected,
    )
    nodes = ns.make_nodes() + [flow_net.make_node(name="flow_network")]

    # add constraints to solver
    # make geometry
    height = 0.1
    width = 0.1
    x, y = Symbol("x"), Symbol("y")
    rec = Rectangle((-width / 2, -height / 2), (width / 2, height / 2))

    # make ldc domain
    ldc_domain = Domain()

    # top wall
    top_wall = PointwiseBoundaryConstraint(
        nodes=nodes,
        geometry=rec,
        outvar={"u": 1.0, "v": 0},
        batch_size=cfg.batch_size.TopWall,
        lambda_weighting={"u": 1.0 - 20 * Abs(x), "v": 1.0},  # weight edges to be zero
        criteria=Eq(y, height / 2),
    )
    ldc_domain.add_constraint(top_wall, "top_wall")

    # no slip
    no_slip = PointwiseBoundaryConstraint(
        nodes=nodes,
        geometry=rec,
        outvar={"u": 0, "v": 0},
        batch_size=cfg.batch_size.NoSlip,
        criteria=y < height / 2,
    )
    ldc_domain.add_constraint(no_slip, "no_slip")

    # interior
    interior = PointwiseInteriorConstraint(
        nodes=nodes,
        geometry=rec,
        outvar={"continuity": 0, "momentum_x": 0, "momentum_y": 0},
        batch_size=cfg.batch_size.Interior,
        lambda_weighting={
            "continuity": Symbol("sdf"),
            "momentum_x": Symbol("sdf"),
            "momentum_y": Symbol("sdf"),
        },
    )
    ldc_domain.add_constraint(interior, "interior")
    
    # add validator
    file_path = "/content/drive/MyDrive/Thesis/Lid_Driven_Cavity/ldc/openfoam/cavity_uniformVel0.csv"
    if os.path.exists(to_absolute_path(file_path)):
        mapping = {"Points:0": "x", "Points:1": "y", "U:0": "u", "U:1": "v", "p": "p"}
        openfoam_var = csv_to_dict(to_absolute_path(file_path), mapping)
        openfoam_var["x"] += -width / 2  # center OpenFoam data
        openfoam_var["y"] += -height / 2  # center OpenFoam data
        openfoam_invar_numpy = {
            key: value for key, value in openfoam_var.items() if key in ["x", "y"]
        }
        openfoam_outvar_numpy = {
            key: value for key, value in openfoam_var.items() if key in ["u", "v"]
        }
        openfoam_validator = PointwiseValidator(
            nodes=nodes,
            invar=openfoam_invar_numpy,
            true_outvar=openfoam_outvar_numpy,
            batch_size=1024,
            plotter=ValidatorPlotter(),
        )
        ldc_domain.add_validator(openfoam_validator)

        # add inferencer data
        grid_inference = PointwiseInferencer(
            nodes=nodes,
            invar=openfoam_invar_numpy,
            output_names=["u", "v", "p"],
            batch_size=1024,
            plotter=InferencerPlotter(),
        )
        ldc_domain.add_inferencer(grid_inference, "inf_data")
    
    # make solver
    slv = Solver(cfg, ldc_domain)

    # start solver
    slv.solve()


if __name__ == "__main__":
    run()